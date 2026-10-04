"""Where the Google sign-in token (the OAuth refresh token) is kept.

Two stores, chosen by the TOKEN_STORE setting:

  keyring -- Windows Credential Manager. The default, used by start.cmd. Encrypted by
             Windows for the logged-in user.
  file    -- a file in the app's data volume. Used in Docker, where a Linux container
             has no Credential Manager. Mode 0600, written atomically.

The file store is less protected than Credential Manager: anyone who can read the data
volume can use the token. The damage is bounded by the token's `drive.file` scope --
it reaches only files this app uploaded. Encrypting the file was rejected: the key
would have to sit next to it for the app to start unattended (spec-docker 3.1).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

KEYRING_SERVICE = "qr-file-share"
KEYRING_USER = "google-refresh-token"


class TokenStore(Protocol):
    def get(self) -> str | None: ...
    def set(self, token: str) -> None: ...
    def delete(self) -> None: ...


class KeyringStore:
    """Windows Credential Manager (or the platform keyring) via `keyring`."""

    def __init__(self, keyring_module=None) -> None:
        if keyring_module is None:
            import keyring as keyring_module  # noqa: PLC0415
        self._k = keyring_module

    def get(self) -> str | None:
        try:
            return self._k.get_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception as exc:  # keyring backends raise their own types
            log.error("Could not read the Google token from Credential Manager: %s", exc)
            return None

    def set(self, token: str) -> None:
        self._k.set_password(KEYRING_SERVICE, KEYRING_USER, token)

    def delete(self) -> None:
        try:
            self._k.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception as exc:
            log.warning("Could not delete the Google token from Credential Manager: %s", exc)


class FileStore:
    """A JSON file readable only by the app's own user."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def get(self) -> str | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.error("Could not read the Google token file %s: %s", self.path, exc)
            return None
        token = data.get("refresh_token") if isinstance(data, dict) else None
        return token or None

    def set(self, token: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        # Create the temp file with 0600 from the start, so the token is never
        # readable by others, not even for the moment before a chmod.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"refresh_token": token}, fh)
        # Atomic: a crash leaves either the old token or the new one, never half a file.
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError as exc:  # e.g. filesystems that do not support POSIX modes
            log.warning("Could not restrict permissions on %s: %s", self.path, exc)

    def delete(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def build_token_store(settings) -> TokenStore:
    if settings.token_store == "file":
        return FileStore(settings.token_file)
    return KeyringStore()
