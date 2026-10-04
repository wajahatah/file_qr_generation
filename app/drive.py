"""Google Drive: sign-in, upload, public sharing, trash and restore.

The rest of the app talks to Drive only through the `DriveClient` protocol. The test
suite substitutes an in-memory fake (tests/fakes.py); nothing in app code knows
about it.

Sign-in uses Google's OAuth flow for desktop apps: a short-lived local web server on
a random port receives Google's redirect. The user signs into *their own* account in
their own browser; this app never sees the password.

Permission is `drive.file`: the app can see and change only files it created itself.
The one credential kept is the OAuth refresh token, in a TokenStore (app/tokens.py):
Windows Credential Manager natively, a 0600 file in the data volume under Docker.

Under Docker there is no browser in the container and a random port is unreachable
from the laptop, so sign-in listens on a fixed, published port and, instead of opening
a browser, hands the Google link to the page to open (spec-docker 3.2).
"""

from __future__ import annotations

import io
import json
import logging
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# KEYRING_SERVICE / KEYRING_USER are re-exported: tests refer to them through this module.
from app.tokens import KEYRING_SERVICE, KEYRING_USER, KeyringStore, TokenStore  # noqa: F401

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_NAME = "QR File Share"
FOLDER_MIME = "application/vnd.google-apps.folder"
SIGN_IN_TIMEOUT_SECONDS = 300


# ---------------------------------------------------------------------- errors


class DriveError(RuntimeError):
    """Drive could not do what was asked. The message is safe to show the user."""


class DriveNotFound(DriveError):
    """The file does not exist any more (deleted by hand, or trash emptied)."""


class DriveNotConnected(DriveError):
    """No Google account is connected, or its sign-in has expired."""


class DriveSetupError(DriveError):
    """client_secret.json is missing or is the wrong kind of OAuth client."""


# --------------------------------------------------------------------- protocol


@dataclass(frozen=True)
class UploadedFile:
    id: str
    url: str


@dataclass(frozen=True)
class ConnectionStatus:
    state: str  # not_set_up | disconnected | connecting | connected | error
    email: str | None = None
    message: str | None = None
    # While connecting, when the app cannot open a browser itself (Docker): the Google
    # sign-in link for the page to open.
    sign_in_url: str | None = None


class DriveClient(Protocol):
    def status(self) -> ConnectionStatus: ...
    def is_connected(self) -> bool: ...
    def start_connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def upload(self, data: bytes, filename: str) -> UploadedFile: ...
    def share_public(self, file_id: str) -> None: ...
    def trash(self, file_id: str) -> None: ...
    def untrash(self, file_id: str) -> None: ...


# ------------------------------------------------------------------ Google Drive


class _LinkCatcher(webbrowser.BaseBrowser):
    """A stand-in 'browser' that records the sign-in link instead of opening it.

    Passed to the sign-in library through its own `browser` hook, so the library's
    tested flow is used unchanged -- only where the link goes differs.
    """

    def __init__(self, name: str, sink) -> None:
        super().__init__(name)
        self._sink = sink

    def open(self, url, new=0, autoraise=True):  # noqa: ARG002 - webbrowser API
        self._sink(url)
        return True


class GoogleDrive:
    """The real client. Construction does no I/O; everything is lazy."""

    def __init__(
        self,
        client_secret_file: Path,
        keyring_module=None,
        *,
        token_store: TokenStore | None = None,
        sign_in_port: int = 0,
        sign_in_bind: str | None = None,
        open_browser: bool = True,
    ) -> None:
        self.client_secret_file = Path(client_secret_file)
        self._tokens: TokenStore = token_store or KeyringStore(keyring_module)
        self._sign_in_port = sign_in_port
        self._sign_in_bind = sign_in_bind
        self._open_browser = open_browser
        self._sign_in_url: str | None = None
        self._catcher_name = f"qr-file-share-link-catcher-{id(self)}"
        if not open_browser:
            webbrowser.register(
                self._catcher_name, None, _LinkCatcher(self._catcher_name, self._caught)
            )

        # googleapiclient service objects are not thread-safe, and routes and the
        # removal sweep both call Drive from worker threads. One lock serialises every
        # Drive call; for a single user that costs nothing noticeable.
        self._api_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._service = None
        self._folder_id: str | None = None
        self._email: str | None = None
        self._connecting = False
        self._last_error: str | None = None

    # ------------------------------------------------------------ configuration

    def _client_config(self) -> dict:
        if not self.client_secret_file.exists():
            raise DriveSetupError(
                f"Google sign-in is not set up yet: {self.client_secret_file.name} "
                "was not found in the app folder. See the setup guide, section 3."
            )
        try:
            cfg = json.loads(self.client_secret_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DriveSetupError(
                f"{self.client_secret_file.name} could not be read: {exc}"
            ) from exc
        if "installed" not in cfg:
            kind = next(iter(cfg), "unknown")
            raise DriveSetupError(
                f"{self.client_secret_file.name} is a '{kind}' OAuth client. It must be "
                "a 'Desktop app' client. See the setup guide, section 3."
            )
        return cfg

    def _refresh_token(self) -> str | None:
        return self._tokens.get()

    def _caught(self, url: str) -> None:
        with self._state_lock:
            self._sign_in_url = url

    # ------------------------------------------------------------ connection

    def is_connected(self) -> bool:
        return self._refresh_token() is not None

    def status(self) -> ConnectionStatus:
        with self._state_lock:
            if self._connecting:
                return ConnectionStatus("connecting", sign_in_url=self._sign_in_url)
            last_error = self._last_error
        try:
            self._client_config()
        except DriveSetupError as exc:
            return ConnectionStatus("not_set_up", message=str(exc))
        if not self.is_connected():
            if last_error:
                return ConnectionStatus("error", message=last_error)
            return ConnectionStatus("disconnected")
        try:
            return ConnectionStatus("connected", email=self._account_email())
        except DriveNotConnected as exc:
            return ConnectionStatus("error", message=str(exc))
        except DriveError:
            # Connected, but Drive is unreachable right now (offline). Still connected.
            return ConnectionStatus("connected", email=self._email)

    def start_connect(self) -> None:
        """Open Google sign-in in the browser. Returns at once; poll status()."""
        cfg = self._client_config()  # fail fast, before starting a thread
        with self._state_lock:
            if self._connecting:
                return
            self._connecting = True
            self._last_error = None
            self._sign_in_url = None
        threading.Thread(
            target=self._run_sign_in, args=(cfg,), name="google-sign-in", daemon=True
        ).start()

    def _run_sign_in(self, cfg: dict) -> None:
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415

        error: str | None = None
        try:
            flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
            creds = flow.run_local_server(
                # Google returns the user to http://localhost:<port>/. Natively the port
                # is any free one (Google allows any loopback port for desktop clients).
                # Under Docker it is fixed and published, and the helper listens on all
                # interfaces inside the container so Docker can forward to it.
                host="localhost",
                bind_addr=self._sign_in_bind,
                port=self._sign_in_port,
                open_browser=True,
                browser=None if self._open_browser else self._catcher_name,
                timeout_seconds=SIGN_IN_TIMEOUT_SECONDS,
                # Always show consent so Google always returns a refresh token, even on
                # a reconnect after Disconnect.
                prompt="consent",
                success_message=(
                    "Google Drive is connected to QR File Share. "
                    "You can close this tab and return to the app."
                ),
            )
            if not creds or not creds.refresh_token:
                raise DriveError("Google did not return a sign-in token. Please try again.")
            self._tokens.set(creds.refresh_token)
            self._reset()
            log.info("Google Drive connected")
        except Exception as exc:
            name = type(exc).__name__
            if name == "WSGITimeoutError":
                error = "Sign-in was not completed within 5 minutes. Please try again."
            elif "access_denied" in str(exc):
                error = "Sign-in was cancelled in the browser."
            else:
                error = f"Sign-in failed: {exc}"
            log.warning("Google sign-in failed: %s: %s", name, exc)
        finally:
            with self._state_lock:
                self._connecting = False
                self._last_error = error
                self._sign_in_url = None

    def disconnect(self) -> None:
        token = self._refresh_token()
        if token:
            # Best effort: tell Google to invalidate the token too, so disconnecting
            # really ends the app's access rather than just forgetting it locally.
            try:
                import requests  # noqa: PLC0415

                requests.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": token},
                    timeout=10,
                )
            except Exception as exc:
                log.warning("Could not revoke the token at Google: %s", exc)
            self._tokens.delete()
        with self._state_lock:
            self._last_error = None
        self._reset()

    def _reset(self) -> None:
        with self._api_lock:
            self._service = None
            self._folder_id = None
            self._email = None

    # ------------------------------------------------------------------ API

    def _svc(self):
        """Return an authorised Drive service. Caller must hold _api_lock."""
        if self._service is not None:
            return self._service
        token = self._refresh_token()
        if not token:
            raise DriveNotConnected("Google Drive is not connected.")
        installed = self._client_config()["installed"]

        from google.oauth2.credentials import Credentials  # noqa: PLC0415
        from googleapiclient.discovery import build  # noqa: PLC0415

        creds = Credentials(
            token=None,  # fetched on first call from the refresh token
            refresh_token=token,
            token_uri=installed.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=installed["client_id"],
            client_secret=installed["client_secret"],
            scopes=SCOPES,
        )
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _call(self, fn):
        """Run fn(service) under the lock, translating Google errors into ours."""
        from google.auth.exceptions import RefreshError, TransportError  # noqa: PLC0415
        from googleapiclient.errors import HttpError  # noqa: PLC0415

        with self._api_lock:
            try:
                return fn(self._svc())
            except RefreshError as exc:
                # Revoked in the Google account, or the 7-day limit on a consent screen
                # left in "Testing" (setup guide, section 3).
                self._service = None
                raise DriveNotConnected(
                    "Google sign-in has expired or was revoked. Reconnect Google Drive."
                ) from exc
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                if status == 404:
                    raise DriveNotFound("The file is no longer in Google Drive.") from exc
                raise DriveError(f"Google Drive error ({status}): {exc.reason}") from exc
            except (TransportError, OSError) as exc:
                raise DriveError(
                    "Could not reach Google Drive. Check the internet connection."
                ) from exc

    def _account_email(self) -> str | None:
        if self._email is None:
            about = self._call(
                lambda s: s.about().get(fields="user(emailAddress)").execute()
            )
            self._email = about.get("user", {}).get("emailAddress")
        return self._email

    def _ensure_folder(self, svc) -> str:
        """The app's own folder. With drive.file the app cannot see folders it did
        not create, so it always uses one it made. Caller must hold _api_lock."""
        if self._folder_id:
            return self._folder_id
        q = (
            f"name = '{FOLDER_NAME}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        )
        found = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()
        files = found.get("files", [])
        if files:
            self._folder_id = files[0]["id"]
        else:
            created = (
                svc.files()
                .create(body={"name": FOLDER_NAME, "mimeType": FOLDER_MIME}, fields="id")
                .execute()
            )
            self._folder_id = created["id"]
        return self._folder_id

    def upload(self, data: bytes, filename: str) -> UploadedFile:
        from googleapiclient.http import MediaIoBaseUpload  # noqa: PLC0415

        def _do(svc):
            folder = self._ensure_folder(svc)
            media = MediaIoBaseUpload(
                io.BytesIO(data), mimetype="application/pdf", resumable=False
            )
            return (
                svc.files()
                .create(
                    body={"name": filename, "parents": [folder]},
                    media_body=media,
                    fields="id, webViewLink",
                )
                .execute()
            )

        try:
            created = self._call(_do)
        except DriveNotFound:
            # The cached folder was deleted by hand. Forget it and try once more.
            self._folder_id = None
            created = self._call(_do)
        return UploadedFile(id=created["id"], url=created["webViewLink"])

    def share_public(self, file_id: str) -> None:
        self._call(
            lambda s: s.permissions()
            .create(fileId=file_id, body={"type": "anyone", "role": "reader"}, fields="id")
            .execute()
        )

    def trash(self, file_id: str) -> None:
        self._call(
            lambda s: s.files()
            .update(fileId=file_id, body={"trashed": True}, fields="id")
            .execute()
        )

    def untrash(self, file_id: str) -> None:
        self._call(
            lambda s: s.files()
            .update(fileId=file_id, body={"trashed": False}, fields="id")
            .execute()
        )
