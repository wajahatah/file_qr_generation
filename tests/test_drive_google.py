"""The real GoogleDrive client, with Google's libraries mocked out.

These cannot prove Google accepts the requests -- only a live sign-in can (spec 13,
"done together at the end"). They do prove what this code sends, how it stores the
credential, and how every Google failure is translated for the user.
"""

from __future__ import annotations

import json
from unittest import mock

import httplib2
import pytest
from googleapiclient.errors import HttpError

from app import drive as D

DESKTOP_CLIENT = {
    "installed": {
        "client_id": "cid.apps.googleusercontent.com",
        "client_secret": "csecret",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "redirect_uris": ["http://localhost"],
    }
}


class FakeKeyring:
    def __init__(self, token=None):
        self.store = {}
        if token:
            self.store[(D.KEYRING_SERVICE, D.KEYRING_USER)] = token

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, value):
        self.store[(service, user)] = value

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


def http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": str(status)}), b"{}")


@pytest.fixture
def secret(tmp_path):
    p = tmp_path / "client_secret.json"
    p.write_text(json.dumps(DESKTOP_CLIENT), encoding="utf-8")
    return p


@pytest.fixture
def svc():
    """A mocked Drive v3 service."""
    s = mock.MagicMock()
    s.files().list().execute.return_value = {"files": []}
    s.files().create().execute.side_effect = [
        {"id": "folder1"},
        {"id": "file1", "webViewLink": "https://drive.google.com/file/d/file1/view?usp=drivesdk"},
    ]
    return s


@pytest.fixture
def gd(secret, svc):
    g = D.GoogleDrive(secret, keyring_module=FakeKeyring(token="refresh-123"))
    g._service = svc  # skip real credential construction for API-shape tests
    return g


# ------------------------------------------------------------------ set-up state


def test_missing_client_secret_is_reported_as_not_set_up(tmp_path):
    g = D.GoogleDrive(tmp_path / "nope.json", keyring_module=FakeKeyring())
    st = g.status()
    assert st.state == "not_set_up"
    assert "nope.json" in st.message and "setup guide" in st.message


def test_wrong_kind_of_oauth_client_is_explained(tmp_path):
    p = tmp_path / "client_secret.json"
    p.write_text(json.dumps({"web": {"client_id": "x"}}), encoding="utf-8")
    st = D.GoogleDrive(p, keyring_module=FakeKeyring()).status()
    assert st.state == "not_set_up" and "Desktop app" in st.message


def test_no_token_means_disconnected(secret):
    g = D.GoogleDrive(secret, keyring_module=FakeKeyring())
    assert not g.is_connected() and g.status().state == "disconnected"


def test_start_connect_fails_fast_without_client_secret(tmp_path):
    g = D.GoogleDrive(tmp_path / "missing.json", keyring_module=FakeKeyring())
    with mock.patch("threading.Thread") as thread:
        with pytest.raises(D.DriveSetupError):
            g.start_connect()
        thread.assert_not_called()


# -------------------------------------------------------------- the credential


def test_credentials_are_built_from_the_stored_refresh_token(secret):
    g = D.GoogleDrive(secret, keyring_module=FakeKeyring(token="refresh-123"))
    with mock.patch("googleapiclient.discovery.build") as build:
        with g._api_lock:
            g._svc()
    creds = build.call_args.kwargs["credentials"]
    assert creds.refresh_token == "refresh-123"
    assert creds.client_id == "cid.apps.googleusercontent.com"
    assert creds.scopes == ["https://www.googleapis.com/auth/drive.file"], "least privilege"
    assert creds.token is None, "no access token is stored anywhere"


def test_sign_in_stores_only_the_refresh_token_in_the_keyring(secret):
    kr = FakeKeyring()
    g = D.GoogleDrive(secret, keyring_module=kr)
    flow = mock.MagicMock()
    flow.run_local_server.return_value = mock.MagicMock(refresh_token="new-refresh", token="access")
    with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_config", return_value=flow):
        g._run_sign_in(DESKTOP_CLIENT)
    assert kr.store == {(D.KEYRING_SERVICE, D.KEYRING_USER): "new-refresh"}
    kwargs = flow.run_local_server.call_args.kwargs
    assert kwargs["port"] == 0 and kwargs["prompt"] == "consent"
    assert kwargs["timeout_seconds"] == D.SIGN_IN_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "exc,expected",
    [
        (type("WSGITimeoutError", (Exception,), {})("t"), "within 5 minutes"),
        (Exception("(access_denied) user said no"), "cancelled"),
        (Exception("boom"), "Sign-in failed"),
    ],
)
def test_sign_in_failures_become_readable_messages(secret, exc, expected):
    g = D.GoogleDrive(secret, keyring_module=FakeKeyring())
    flow = mock.MagicMock()
    flow.run_local_server.side_effect = exc
    with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_config", return_value=flow):
        g._run_sign_in(DESKTOP_CLIENT)
    st = g.status()
    assert st.state == "error" and expected in st.message


def test_disconnect_revokes_at_google_and_forgets_locally(secret):
    kr = FakeKeyring(token="refresh-123")
    g = D.GoogleDrive(secret, keyring_module=kr)
    with mock.patch("requests.post") as post:
        g.disconnect()
    post.assert_called_once()
    assert post.call_args.kwargs["params"] == {"token": "refresh-123"}
    assert kr.store == {}


def test_disconnect_still_forgets_locally_if_google_is_unreachable(secret):
    kr = FakeKeyring(token="refresh-123")
    g = D.GoogleDrive(secret, keyring_module=kr)
    with mock.patch("requests.post", side_effect=OSError("offline")):
        g.disconnect()
    assert kr.store == {}


# ----------------------------------------------------------------- API calls


def test_upload_creates_the_app_folder_then_the_file_inside_it(gd, svc):
    up = gd.upload(b"%PDF-1.4 x", "Quote.pdf")
    assert up == D.UploadedFile("file1", "https://drive.google.com/file/d/file1/view?usp=drivesdk")
    creates = [c.kwargs for c in svc.files().create.call_args_list if c.kwargs]
    folder_body, file_body = creates[0]["body"], creates[1]["body"]
    assert folder_body == {"name": "QR File Share", "mimeType": D.FOLDER_MIME}
    assert file_body == {"name": "Quote.pdf", "parents": ["folder1"]}
    assert creates[1]["fields"] == "id, webViewLink"


def test_existing_app_folder_is_reused(gd, svc):
    svc.files().list().execute.return_value = {"files": [{"id": "existing"}]}
    svc.files().create().execute.side_effect = [
        {"id": "f", "webViewLink": "https://drive.google.com/file/d/f/view"},
        {"id": "g", "webViewLink": "https://drive.google.com/file/d/g/view"},
    ]
    gd.upload(b"%PDF", "a.pdf")
    gd.upload(b"%PDF", "b.pdf")
    bodies = [c.kwargs["body"] for c in svc.files().create.call_args_list if c.kwargs]
    assert all(b["parents"] == ["existing"] for b in bodies)
    assert not any(b.get("mimeType") == D.FOLDER_MIME for b in bodies)


def test_upload_recovers_when_the_folder_was_deleted_by_hand(gd, svc):
    gd._folder_id = "stale"
    svc.files().list().execute.return_value = {"files": []}
    svc.files().create().execute.side_effect = [
        http_error(404),  # upload into the stale folder
        {"id": "fresh-folder"},
        {"id": "f", "webViewLink": "https://drive.google.com/file/d/f/view"},
    ]
    assert gd.upload(b"%PDF", "a.pdf").id == "f"
    assert gd._folder_id == "fresh-folder"


def test_share_makes_it_readable_by_anyone_with_the_link_and_no_more(gd, svc):
    gd.share_public("file1")
    kw = svc.permissions().create.call_args.kwargs
    assert kw["fileId"] == "file1"
    assert kw["body"] == {"type": "anyone", "role": "reader"}, "never writer, never discoverable"


def test_trash_and_untrash(gd, svc):
    gd.trash("file1")
    assert svc.files().update.call_args.kwargs["body"] == {"trashed": True}
    gd.untrash("file1")
    assert svc.files().update.call_args.kwargs["body"] == {"trashed": False}


# ------------------------------------------------------------ error translation


def test_404_becomes_not_found(gd, svc):
    svc.files().update().execute.side_effect = http_error(404)
    with pytest.raises(D.DriveNotFound):
        gd.trash("gone")


def test_other_http_errors_become_drive_errors(gd, svc):
    svc.files().update().execute.side_effect = http_error(500)
    with pytest.raises(D.DriveError) as e:
        gd.trash("x")
    assert not isinstance(e.value, D.DriveNotFound) and "500" in str(e.value)


def test_revoked_or_expired_sign_in_asks_to_reconnect(gd, svc):
    from google.auth.exceptions import RefreshError

    svc.files().update().execute.side_effect = RefreshError("invalid_grant")
    with pytest.raises(D.DriveNotConnected, match="Reconnect"):
        gd.trash("x")
    assert gd._service is None, "the dead service must be rebuilt after reconnecting"


def test_network_failure_is_explained(gd, svc):
    svc.files().update().execute.side_effect = OSError("no route to host")
    with pytest.raises(D.DriveError, match="internet connection"):
        gd.trash("x")


def test_not_connected_without_a_token(secret):
    g = D.GoogleDrive(secret, keyring_module=FakeKeyring())
    with pytest.raises(D.DriveNotConnected):
        g.trash("x")
