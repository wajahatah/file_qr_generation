"""Sign-in, sessions, and the defences in spec section 10.

The app listens only on 127.0.0.1, but any web page open in the same browser can make
the browser send requests to localhost. These tests pin the defences against that.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.main import app
from tests.conftest import ADMIN_TOKEN, AUTH, ORIGIN, TZ

APP_DIR = Path(__file__).resolve().parent.parent / "app"


def login(client, token=ADMIN_TOKEN, headers=ORIGIN):
    return client.post("/admin/login", data={"token": token}, headers=headers, follow_redirects=False)


# ------------------------------------------------------------------- signing in


def test_app_page_needs_a_session(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"


def test_root_goes_to_the_app(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/admin"


def test_wrong_token_sets_no_cookie(client):
    r = login(client, token="wrong")
    assert r.status_code == 401
    assert "set-cookie" not in r.headers
    assert "not right" in r.text


def test_right_token_sets_a_hardened_cookie(client):
    r = login(client)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert re.search(r"SameSite=strict", cookie, re.I)
    assert "Max-Age=43200" in cookie  # 12 hours
    assert "Secure" not in cookie, "a Secure cookie over plain http is never sent back"


def test_cookie_is_secure_over_https(env, drive):
    app.state.drive_override, app.state.tz = drive, TZ
    try:
        with TestClient(app, base_url="https://testserver") as c:
            r = c.post("/admin/login", data={"token": ADMIN_TOKEN},
                       headers={"Origin": "https://testserver"}, follow_redirects=False)
            assert "Secure" in r.headers["set-cookie"]
    finally:
        del app.state.drive_override, app.state.tz


def test_only_a_hash_of_the_session_is_stored(session, env):
    raw = session.cookies.get("qfs_session")
    conn = db.connect(env.db_path)
    stored = [r["id_hash"] for r in conn.execute("SELECT id_hash FROM admin_sessions")]
    conn.close()
    assert raw and stored and raw not in stored
    assert len(stored[0]) == 64  # sha256 hex


def test_session_opens_the_app_and_the_api(session):
    assert session.get("/admin").status_code == 200
    assert session.get("/api/status").status_code == 200


def test_expired_session_is_refused(session, env):
    conn = db.connect(env.db_path)
    conn.execute("UPDATE admin_sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    conn.commit()
    conn.close()
    assert session.get("/api/status").status_code == 401


def test_logout_kills_the_session_server_side(session):
    old = session.cookies.get("qfs_session")
    r = session.post("/admin/logout", follow_redirects=False)
    assert r.status_code == 303
    # Even if a copy of the old cookie survives somewhere, it is dead.
    session.cookies.set("qfs_session", old)
    assert session.get("/api/status").status_code == 401


# ----------------------------------------------------------- forged requests


def test_cookie_post_without_origin_is_refused(session):
    del session.headers["Origin"]
    assert session.post("/api/maintenance/sweep").status_code == 403


def test_cookie_post_from_another_site_is_refused(session):
    r = session.post("/api/maintenance/sweep", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_cookie_post_from_this_app_is_allowed(session):
    assert session.post("/api/maintenance/sweep").status_code == 200


def test_cookie_get_needs_no_origin(session):
    del session.headers["Origin"]
    assert session.get("/api/status").status_code == 200


def test_bearer_post_needs_no_origin(client):
    """curl and scripts keep working exactly as before."""
    assert client.post("/api/maintenance/sweep", headers=AUTH).status_code == 200


def test_wrong_bearer_is_refused_even_with_a_valid_cookie(session):
    r = session.get("/api/status", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_login_from_another_site_is_refused(client):
    assert login(client, headers={"Origin": "https://evil.example"}).status_code == 403


def test_no_credentials_is_refused(client):
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/links").status_code == 401


# -------------------------------------------------------------- DNS rebinding


def test_foreign_host_header_is_refused(client):
    r = client.get("/api/status", headers={**AUTH, "Host": "attacker.example"})
    assert r.status_code == 400


def test_localhost_hosts_are_accepted(client):
    for host in ("localhost:8000", "127.0.0.1:8000", "localhost"):
        assert client.get("/healthz", headers={"Host": host}).status_code == 200


# ------------------------------------------------------------ response headers


def test_app_pages_carry_security_headers(client):
    r = client.get("/admin/login")
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_referrer_policy_does_not_break_the_origin_check(client):
    """Regression, found in the full-system browser run: with `no-referrer`, browsers
    send `Origin: null` on every POST, and the CSRF check refuses them all -- sign-in
    and every save in the app. The unit tests could not see it because they set the
    Origin header by hand."""
    policy = client.get("/admin/login").headers["referrer-policy"]
    assert policy == "same-origin"


def test_null_origin_is_still_refused(session):
    """Fixing the policy must not be done by accepting null: sandboxed frames and
    cross-site redirects send null, so accepting it would let forgeries through."""
    r = session.post("/api/maintenance/sweep", headers={"Origin": "null"})
    assert r.status_code == 403


def test_static_files_are_revalidated_so_updates_take_effect(client):
    """Regression, found in the browser run: a stale cached stylesheet survived a
    change on the server. After an update, the page must never run old script."""
    for path in ("/static/admin.js", "/static/admin.css", "/sw.js"):
        r = client.get(path)
        assert r.headers["cache-control"] == "no-cache", path
        assert "etag" in r.headers, "revalidation needs an ETag to answer 304 cheaply"


def test_api_responses_are_not_cached(client):
    assert client.get("/api/status", headers=AUTH).headers["cache-control"] == "no-store"


# ---------------------------------------------- the pages obey their own policy


def test_templates_have_no_inline_script_or_style():
    """The CSP forbids inline code, so any inline script or style attribute would
    silently not work. Catch it here rather than in the browser."""
    for tpl in (APP_DIR / "templates").glob("*.html"):
        html = tpl.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), f"inline <script> in {tpl.name}"
        assert " style=" not in html, f"inline style attribute in {tpl.name}"
        assert not re.search(r"\son[a-z]+=", html), f"inline event handler in {tpl.name}"


def test_javascript_never_injects_html():
    """Untrusted text must go in via textContent. Any of these would parse it as HTML."""
    sinks = re.compile(r"\.(innerHTML|outerHTML)\s*[+]?=|insertAdjacentHTML|document\.write|\beval\(")
    for js in (APP_DIR / "static").glob("*.js"):
        code = js.read_text(encoding="utf-8")
        assert not sinks.search(code), f"{js.name}: {sinks.search(code).group(0)}"


def test_label_cannot_inject_markup_into_the_print_page(session, invoice_pdf):
    from tests.conftest import upload

    evil = '<script>alert("x")</script>'
    link = upload(session, invoice_pdf, label=evil).json()
    page = session.get(f"/admin/print/{link['id']}").text
    assert evil not in page
    assert "&lt;script&gt;" in page


def test_app_and_print_pages_render(session, invoice_pdf):
    from tests.conftest import upload

    assert "New QR code" in session.get("/admin").text
    link = upload(session, invoice_pdf, label="Quotation 42").json()
    page = session.get(f"/admin/print/{link['id']}").text
    assert "Quotation 42" in page and "Scan with your phone camera" in page
    assert 'data-live="1"' in page


def test_service_worker_and_manifest_are_served(client):
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    manifest = client.get("/static/manifest.webmanifest").json()
    assert manifest["start_url"] == "/admin" and manifest["display"] == "standalone"
    sizes = {i["sizes"] for i in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200, icon["src"]
