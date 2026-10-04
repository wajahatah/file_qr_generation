"""The HTTP API, end to end through FastAPI, against the fake Drive."""

from __future__ import annotations

import hashlib
import io
from datetime import date, datetime, timedelta

from PIL import Image
from pyzbar.pyzbar import decode

from app import db
from app.limits import expiry_instant, local_today, utcnow
from tests.conftest import AUTH, TZ, upload


def today() -> date:
    return local_today(utcnow(), TZ)


def scan(png: bytes) -> str:
    """Decode a QR image the way a phone camera would."""
    results = decode(Image.open(io.BytesIO(png)))
    assert len(results) == 1, f"expected one QR code, found {len(results)}"
    return results[0].data.decode("utf-8")


# -------------------------------------------------------------- the whole journey


def test_every_sample_pdf_becomes_a_scannable_qr_for_the_exact_file(client, drive, sample_pdfs):
    """Upload -> QR image -> decode the pixels -> the link opens exactly this file."""
    for pdf in sample_pdfs:
        original = pdf.read_bytes()
        r = upload(client, pdf)
        assert r.status_code == 201, r.text
        link = r.json()

        png = client.get(f"/api/links/{link['id']}/qr.png", headers=AUTH).content
        scanned = scan(png)
        assert scanned == link["drive_url"], "the QR must encode the Drive link"

        fid = scanned.split("/file/d/")[1].split("/")[0]
        assert drive.reachable(fid)
        stored = drive.files[fid]["data"]
        assert hashlib.sha256(stored).digest() == hashlib.sha256(original).digest(), pdf.name


def test_the_qr_never_points_at_the_laptop(client, invoice_pdf):
    link = upload(client, invoice_pdf).json()
    scanned = scan(client.get(f"/api/links/{link['id']}/qr.png", headers=AUTH).content)
    assert scanned.startswith("https://drive.google.com/")
    for local in ("localhost", "127.0.0.1", "192.168.", "10.0."):
        assert local not in scanned


# ------------------------------------------------------------------- upload rules


def test_rejects_non_pdf_by_magic_bytes(client, tmp_path):
    fake = tmp_path / "not-really.pdf"
    fake.write_bytes(b"MZ\x90\x00 this is a windows executable")
    r = upload(client, fake)
    assert r.status_code == 415
    assert "PDF" in r.json()["detail"]


def test_rejects_empty_upload(client, tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    assert upload(client, empty).status_code == 400


def test_rejects_oversized_upload(client, tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")
    get_settings.cache_clear()
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.4" + b"\x00" * 4096)
    assert upload(client, big).status_code == 413


def test_upload_without_drive_connected_is_refused_cleanly(client, drive, invoice_pdf, env):
    drive.connected = False
    r = upload(client, invoice_pdf)
    assert r.status_code == 409
    assert "Connect Google Drive" in r.json()["detail"]
    assert drive.files == {}


def test_drive_failure_is_reported_not_hidden(client, drive, invoice_pdf):
    drive.fail_on.add("upload")
    r = upload(client, invoice_pdf)
    assert r.status_code == 502
    assert "Drive" in r.json()["detail"]


def test_label_is_trimmed_and_optional(client, invoice_pdf):
    assert upload(client, invoice_pdf, label="  Quotation 7  ").json()["label"] == "Quotation 7"
    assert upload(client, invoice_pdf).json()["label"] is None


def test_hostile_filenames_are_cleaned(client, tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    with open(pdf, "rb") as fh:
        r = client.post(
            "/api/links",
            headers=AUTH,
            files={"file": ("..\\..\\windows\\evil", fh, "application/pdf")},
            data={"preset_days": "7"},
        )
    assert r.json()["filename"] == "evil.pdf"


# ------------------------------------------------------------------ choosing limits


def test_every_preset_sets_the_right_last_day(client, invoice_pdf):
    for days in (1, 3, 7, 30):
        link = upload(client, invoice_pdf, preset_days=days).json()
        assert link["last_day"] == (today() + timedelta(days=days)).isoformat(), days
        assert link["status"]["state"] == "active"


def test_a_picked_date_sets_that_day(client, invoice_pdf):
    target = today() + timedelta(days=45)
    link = upload(client, invoice_pdf, until=target.isoformat()).json()
    assert link["last_day"] == target.isoformat()


def test_limit_choice_errors(client, invoice_pdf):
    past = (today() - timedelta(days=1)).isoformat()
    too_far = (today() + timedelta(days=366)).isoformat()
    assert upload(client, invoice_pdf, until=past).status_code == 400
    assert upload(client, invoice_pdf, until=too_far).status_code == 400
    assert upload(client, invoice_pdf, preset_days=5).status_code == 400
    both = upload(client, invoice_pdf, preset_days=7, until=today().isoformat())
    assert both.status_code == 400


def test_preview_sentence_matches_what_is_then_stored(client, invoice_pdf):
    preview = client.post("/api/limits/preview", json={"preset_days": 30}, headers=AUTH).json()
    link = upload(client, invoice_pdf, preset_days=30).json()
    assert preview["last_day"] == link["last_day"]
    assert preview["sentence"].startswith("Customers can open this until ")
    assert preview["sentence"].endswith("11:59 PM (30 days)")


# ------------------------------------------------------------- managing links


def test_list_is_newest_first(client, sample_pdfs):
    ids = [upload(client, p).json()["id"] for p in sample_pdfs]
    listed = [l["id"] for l in client.get("/api/links", headers=AUTH).json()["links"]]
    assert listed == list(reversed(ids))


def test_change_limit_via_api(client, invoice_pdf):
    link = upload(client, invoice_pdf, preset_days=7).json()
    preview = client.post(f"/api/links/{link['id']}/limit/preview", json={"extend_days": 30}, headers=AUTH).json()
    changed = client.post(f"/api/links/{link['id']}/limit", json={"extend_days": 30}, headers=AUTH).json()
    assert changed["last_day"] == preview["last_day"] == (today() + timedelta(days=37)).isoformat()
    assert changed["drive_url"] == link["drive_url"]


def test_end_now_via_api(client, drive, invoice_pdf):
    link = upload(client, invoice_pdf).json()
    out = client.post(f"/api/links/{link['id']}/end", headers=AUTH).json()
    assert out["removed_from_drive"] is True
    assert out["status"]["state"] == "ended"
    assert not any(drive.reachable(f) for f in drive.files)


def test_reactivate_via_api(client, drive, invoice_pdf, env):
    link = upload(client, invoice_pdf).json()
    conn = db.connect(env.db_path)
    db.set_expiry(conn, link["id"], expiry_instant(today() - timedelta(days=1), TZ))
    conn.close()
    swept = client.post("/api/maintenance/sweep", headers=AUTH).json()
    assert swept["removed"] == 1

    gone = client.get(f"/api/links/{link['id']}", headers=AUTH).json()
    assert gone["status"]["state"] == "expired" and gone["actions"]["reactivate"]

    back = client.post(f"/api/links/{link['id']}/reactivate", json={"preset_days": 7}, headers=AUTH).json()
    assert back["status"]["state"] == "active"
    assert back["drive_url"] == link["drive_url"]


def test_unknown_link_is_404(client):
    for method, path in [("get", "/api/links/999"), ("get", "/api/links/999/qr.png"),
                         ("post", "/api/links/999/end")]:
        assert getattr(client, method)(path, headers=AUTH).status_code == 404


# ------------------------------------------------------------------ settings


def test_default_limit_is_saved_and_offered(client):
    assert client.get("/api/settings", headers=AUTH).json()["default_preset_days"] == 7
    client.put("/api/settings", json={"default_preset_days": 30}, headers=AUTH)
    status = client.get("/api/status", headers=AUTH).json()
    assert status["limits"]["default_preset_days"] == 30


def test_default_limit_must_be_a_preset(client):
    assert client.put("/api/settings", json={"default_preset_days": 5}, headers=AUTH).status_code == 400


def test_changing_the_default_does_not_touch_existing_links(client, invoice_pdf):
    link = upload(client, invoice_pdf, preset_days=7).json()
    client.put("/api/settings", json={"default_preset_days": 1}, headers=AUTH)
    assert client.get(f"/api/links/{link['id']}", headers=AUTH).json()["last_day"] == link["last_day"]


# -------------------------------------------------------------------- status


def test_status_reports_drive_and_date_bounds(client):
    s = client.get("/api/status", headers=AUTH).json()
    # sign_in_url added by spec-docker (additive; None except while a Docker sign-in runs).
    assert s["drive"] == {
        "state": "connected",
        "email": "tester@example.com",
        "message": None,
        "sign_in_url": None,
    }
    assert s["limits"]["presets"] == [1, 3, 7, 30]
    assert s["limits"]["today"] == today().isoformat()
    assert s["limits"]["max_day"] == (today() + timedelta(days=365)).isoformat()


def test_limits_that_ran_out_while_the_laptop_was_off_are_removed_at_startup(env, drive, invoice_pdf):
    """The core promise of section 5: starting the app catches up immediately."""
    from fastapi.testclient import TestClient

    from app.main import app

    db.init_db(env.db_path)
    conn = db.connect(env.db_path)
    up = drive.upload(invoice_pdf.read_bytes(), "q.pdf")
    drive.share_public(up.id)
    db.insert_link(
        conn, drive_file_id=up.id, drive_url=up.url, filename="q.pdf", size_bytes=1,
        sha256="x", label=None, expires_at=datetime.now(TZ) - timedelta(hours=1),
    )
    conn.close()
    assert drive.reachable(up.id)

    app.state.drive_override = drive
    app.state.tz = TZ
    try:
        with TestClient(app) as c:
            # The first sweep runs as the app starts; wait for it deterministically.
            for _ in range(50):
                if app.state.last_sweep:
                    break
                c.get("/healthz")
            assert app.state.last_sweep and app.state.last_sweep["removed"] == 1
    finally:
        del app.state.drive_override
        del app.state.tz
    assert not drive.reachable(up.id)


def test_status_warns_when_expired_links_are_stuck(client, drive, invoice_pdf, env):
    link = upload(client, invoice_pdf).json()
    conn = db.connect(env.db_path)
    db.set_expiry(conn, link["id"], expiry_instant(today() - timedelta(days=1), TZ))
    conn.close()
    drive.connected = False
    client.post("/api/maintenance/sweep", headers=AUTH)
    s = client.get("/api/status", headers=AUTH).json()["last_sweep"]
    assert s["pending"] == 1 and s["drive_not_connected"] is True
