"""Google sign-in, native vs Docker (spec-docker 3.2).

Native: any free port, the app opens the browser. Docker: fixed published port,
listening on all interfaces inside the container, and the link handed to the page.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from unittest import mock

import pytest

from app import drive as D
from app.tokens import FileStore

CLIENT = {
    "installed": {
        "client_id": "cid", "client_secret": "cs",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "redirect_uris": ["http://localhost"],
    }
}
AUTH_URL = "https://accounts.google.com/o/oauth2/auth?client_id=cid&state=xyz"


@pytest.fixture
def secret(tmp_path):
    p = tmp_path / "client_secret.json"
    p.write_text(json.dumps(CLIENT), encoding="utf-8")
    return p


def _flow_that_opens_the_browser(finish: threading.Event | None = None):
    """A stand-in flow that behaves like the real run_local_server: it hands the auth
    link to webbrowser.get(browser).open(), then waits for Google to come back."""
    flow = mock.MagicMock()

    def run_local_server(**kw):
        webbrowser.get(kw.get("browser")).open(AUTH_URL, new=1, autoraise=True)
        if finish is not None:
            finish.wait(5)
        return mock.MagicMock(refresh_token="refresh-new")

    flow.run_local_server.side_effect = run_local_server
    return flow


def test_native_mode_is_unchanged(secret):
    g = D.GoogleDrive(secret, token_store=FileStore(secret.parent / "t.json"))
    flow = mock.MagicMock()
    flow.run_local_server.return_value = mock.MagicMock(refresh_token="r")
    with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_config", return_value=flow):
        g._run_sign_in(CLIENT)
    kw = flow.run_local_server.call_args.kwargs
    assert kw["port"] == 0 and kw["bind_addr"] is None and kw["browser"] is None
    assert kw["host"] == "localhost" and kw["open_browser"] is True


def test_docker_mode_uses_the_published_port_and_all_interfaces(secret):
    g = D.GoogleDrive(
        secret, token_store=FileStore(secret.parent / "t.json"),
        sign_in_port=8766, sign_in_bind="0.0.0.0", open_browser=False,
    )
    flow = _flow_that_opens_the_browser()
    with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_config", return_value=flow):
        g._run_sign_in(CLIENT)
    kw = flow.run_local_server.call_args.kwargs
    assert kw["port"] == 8766 and kw["bind_addr"] == "0.0.0.0"
    # Google must send the user back to localhost, not 0.0.0.0.
    assert kw["host"] == "localhost"
    assert kw["browser"] is not None, "the link must go to the page, not a real browser"


def test_docker_sign_in_link_reaches_the_page_while_connecting(secret):
    """The link is visible in status() during sign-in, and gone afterwards."""
    store = FileStore(secret.parent / "t.json")
    g = D.GoogleDrive(secret, token_store=store, sign_in_port=8766,
                      sign_in_bind="0.0.0.0", open_browser=False)
    finish = threading.Event()
    flow = _flow_that_opens_the_browser(finish)
    with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_config", return_value=flow), \
         mock.patch("webbrowser.open") as real_browser:
        g.start_connect()
        for _ in range(100):
            st = g.status()
            if st.sign_in_url:
                break
            threading.Event().wait(0.02)
        assert st.state == "connecting" and st.sign_in_url == AUTH_URL
        real_browser.assert_not_called()  # nothing tried to open a browser in the container

        finish.set()  # Google redirects back
        for _ in range(100):
            if g.status().state != "connecting":
                break
            threading.Event().wait(0.02)

    assert store.get() == "refresh-new", "token saved to the Docker file store"
    assert g.status().sign_in_url is None


def test_docker_disconnect_deletes_the_token_file(secret):
    store = FileStore(secret.parent / "t.json")
    store.set("refresh-abc")
    g = D.GoogleDrive(secret, token_store=store, open_browser=False)
    with mock.patch("requests.post"):
        g.disconnect()
    assert store.get() is None and not store.path.exists()
