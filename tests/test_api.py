"""HTTP layer: auth, upload validation, and the uniform-404 guarantee."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import db
from tests.conftest import AUTH


def upload(client, path, **form):
    with open(path, "rb") as fh:
        return client.post(
            "/api/files",
            headers=AUTH,
            files={"file": (path.name, fh, "application/pdf")},
            data=form,
        )


# ----------------------------------------------------------------------- liveness


def test_healthz(client) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


# --------------------------------------------------------------------------- auth


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": "test-admin-token"},  # missing the Bearer scheme
        {"Authorization": "Basic test-admin-token"},
        {"Authorization": "Bearer "},
    ],
)
def test_admin_routes_reject_bad_credentials(client, headers, invoice_pdf) -> None:
    with open(invoice_pdf, "rb") as fh:
        r = client.post(
            "/api/files", headers=headers, files={"file": ("x.pdf", fh, "application/pdf")}
        )
    assert r.status_code == 401


def test_admin_routes_accept_the_configured_token(client, invoice_pdf) -> None:
    assert upload(client, invoice_pdf).status_code == 201


def test_public_download_route_needs_no_auth(client, invoice_pdf) -> None:
    token = upload(client, invoice_pdf).json()["token"]
    assert client.get(f"/d/{token}").status_code == 200


# --------------------------------------------------------------- upload validation


def test_rejects_non_pdf_by_magic_bytes(client, tmp_path) -> None:
    """A .pdf extension is not evidence. The first five bytes are."""
    fake = tmp_path / "not-really.pdf"
    fake.write_bytes(b"MZ\x90\x00 this is a windows executable")
    r = upload(client, fake)
    assert r.status_code == 415
    assert "PDF" in r.json()["detail"]


def test_rejects_empty_upload(client, tmp_path) -> None:
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    assert upload(client, empty).status_code == 400


def test_rejects_oversized_upload(client, tmp_path, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")
    get_settings.cache_clear()
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.4" + b"\x00" * 4096)
    assert upload(client, big).status_code == 413


@pytest.mark.parametrize("field,value", [("max_downloads", 0), ("expires_in_days", 0)])
def test_rejects_nonsensical_limits(client, invoice_pdf, field, value) -> None:
    r = upload(client, invoice_pdf, **{field: value})
    assert r.status_code == 400


def test_upload_returns_token_url_and_qr(client, invoice_pdf) -> None:
    body = upload(client, invoice_pdf).json()
    assert len(body["token"]) == 22
    assert body["url"] == f"https://qr.test/d/{body['token']}"
    assert body["qr_png_base64"]
    assert body["expires_at"] is not None  # 30-day default applied


def test_no_expiry_flag_produces_a_permanent_link(client, invoice_pdf) -> None:
    body = upload(client, invoice_pdf, no_expiry="true").json()
    assert body["expires_at"] is None


def test_explicit_expiry_overrides_the_default(client, invoice_pdf) -> None:
    body = upload(client, invoice_pdf, expires_in_days=1).json()
    expires = datetime.fromisoformat(body["expires_at"])
    assert expires < datetime.now(timezone.utc) + timedelta(days=2)


# -------------------------------------------------------- the uniform-404 guarantee


def _make_failing_links(client, invoice_pdf, conn):
    """One token per failure mode, all of which must look identical from outside.

    Each UPDATE is committed before the next HTTP call: an uncommitted write holds
    SQLite's write lock, and the request would block on it until busy_timeout.
    """
    expired = upload(client, invoice_pdf).json()["token"]
    revoked = upload(client, invoice_pdf).json()["token"]
    exhausted = upload(client, invoice_pdf, max_downloads=1).json()["token"]

    conn.execute(
        "UPDATE links SET expires_at = ? WHERE token = ?",
        ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), expired),
    )
    conn.execute(
        "UPDATE links SET revoked_at = ? WHERE token = ?", (db.now_iso(), revoked)
    )
    conn.commit()

    client.get(f"/d/{exhausted}")  # burn the single download
    return {
        db.OUTCOME_EXPIRED: expired,
        db.OUTCOME_REVOKED: revoked,
        db.OUTCOME_EXHAUSTED: exhausted,
        db.OUTCOME_NOT_FOUND: "nonexistenttoken000000",
    }


def test_all_failure_modes_are_externally_indistinguishable(
    client, invoice_pdf, conn
) -> None:
    cases = _make_failing_links(client, invoice_pdf, conn)
    responses = {reason: client.get(f"/d/{tok}") for reason, tok in cases.items()}

    for reason, r in responses.items():
        assert r.status_code == 404, reason

    bodies = {r.text for r in responses.values()}
    assert len(bodies) == 1, "failure pages differ; that leaks which tokens exist"

    # And the page must not name the reason.
    page = next(iter(bodies)).lower()
    for word in ("expired", "revoked", "exhausted", "not found", "limit"):
        assert word not in page, f"error page leaks the reason: {word!r}"


def test_the_log_still_records_the_true_reason(client, invoice_pdf, conn) -> None:
    """Opaque to the visitor, precise in the log. That is the whole design."""
    cases = _make_failing_links(client, invoice_pdf, conn)
    for reason, tok in cases.items():
        client.get(f"/d/{tok}")
        outcomes = [e["outcome"] for e in db.access_log_for(conn, tok)]
        assert reason in outcomes, f"{reason} was not logged for {tok}"


# ----------------------------------------------------------------- admin endpoints


def test_metadata_never_exposes_the_storage_ref(client, invoice_pdf) -> None:
    token = upload(client, invoice_pdf).json()["token"]
    meta = client.get(f"/api/files/{token}", headers=AUTH).json()
    assert "storage_ref" not in meta
    assert meta["status"] == db.OUTCOME_SERVED
    assert meta["url"].endswith(token)


def test_metadata_reports_download_count(client, invoice_pdf) -> None:
    token = upload(client, invoice_pdf).json()["token"]
    for _ in range(3):
        client.get(f"/d/{token}")
    assert client.get(f"/api/files/{token}", headers=AUTH).json()["download_count"] == 3


def test_revoke_endpoint_kills_a_live_link(client, invoice_pdf) -> None:
    token = upload(client, invoice_pdf).json()["token"]
    assert client.get(f"/d/{token}").status_code == 200
    r = client.post(f"/api/files/{token}/revoke", headers=AUTH).json()
    assert r["revoked"] is True and r["already_revoked"] is False
    assert client.get(f"/d/{token}").status_code == 404
    assert (
        client.post(f"/api/files/{token}/revoke", headers=AUTH).json()["already_revoked"]
        is True
    )


def test_log_endpoint_separates_served_from_attempts(client, invoice_pdf) -> None:
    token = upload(client, invoice_pdf, max_downloads=2).json()["token"]
    for _ in range(5):
        client.get(f"/d/{token}")
    log = client.get(f"/api/files/{token}/log", headers=AUTH).json()
    assert log["served"] == 2
    assert log["attempts"] == 5


def test_log_truncates_the_caller_ip(client, invoice_pdf) -> None:
    token = upload(client, invoice_pdf).json()["token"]
    client.get(f"/d/{token}")
    entry = client.get(f"/api/files/{token}/log", headers=AUTH).json()["entries"][0]
    assert entry["ip"] is None or entry["ip"].endswith(("/24", "/64"))


def test_qr_endpoint_returns_a_png(client, invoice_pdf) -> None:
    token = upload(client, invoice_pdf).json()["token"]
    r = client.get(f"/api/files/{token}/qr.png", headers=AUTH)
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_admin_lookups_404_on_unknown_token(client) -> None:
    for path in ("", "/log", "/qr.png"):
        assert client.get(f"/api/files/unknown000000000000{path}", headers=AUTH).status_code == 404
    assert client.post("/api/files/unknown000000000000/revoke", headers=AUTH).status_code == 404


def test_list_endpoint_returns_uploads(client, sample_pdfs) -> None:
    for pdf in sample_pdfs:
        upload(client, pdf)
    links = client.get("/api/files", headers=AUTH).json()["links"]
    assert len(links) == len(sample_pdfs)
    assert all("storage_ref" not in link for link in links)


def test_download_sets_protective_headers(client, invoice_pdf) -> None:
    token = upload(client, invoice_pdf).json()["token"]
    r = client.get(f"/d/{token}")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "90374749.pdf" in r.headers["content-disposition"]
