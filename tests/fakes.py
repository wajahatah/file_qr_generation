"""An in-memory stand-in for Google Drive.

It implements the same DriveClient protocol as app.drive.GoogleDrive, so the whole
app runs against it with no network and no Google account. It exists only in the
test suite; nothing in app/ refers to it.

`reachable(file_id)` answers the question that matters to a customer: if someone
scans this QR code right now, do they get the file?
"""

from __future__ import annotations

from app.drive import (
    ConnectionStatus,
    DriveError,
    DriveNotConnected,
    DriveNotFound,
    UploadedFile,
)


class FakeDrive:
    def __init__(self) -> None:
        self.files: dict[str, dict] = {}
        self.connected = True
        # Operations to fail: any of "upload", "share", "trash", "untrash".
        self.fail_on: set[str] = set()
        # When True, a failing share still takes effect at "Google" before the error
        # comes back -- the case of a connection dropping after the request went out.
        self.share_applies_before_fail = False
        self.connect_calls = 0
        self._n = 0

    # --- connection -----------------------------------------------------------

    def status(self) -> ConnectionStatus:
        if self.connected:
            return ConnectionStatus("connected", email="tester@example.com")
        return ConnectionStatus("disconnected")

    def is_connected(self) -> bool:
        return self.connected

    def start_connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    # --- files ----------------------------------------------------------------

    def _check(self, op: str) -> None:
        if not self.connected:
            raise DriveNotConnected("Google Drive is not connected.")
        if op in self.fail_on:
            raise DriveError(f"Simulated Drive failure during {op}.")

    def _get(self, file_id: str) -> dict:
        f = self.files.get(file_id)
        if f is None or f["purged"]:
            raise DriveNotFound("The file is no longer in Google Drive.")
        return f

    def upload(self, data: bytes, filename: str) -> UploadedFile:
        self._check("upload")
        self._n += 1
        fid = f"fakefile{self._n:04d}"
        self.files[fid] = {
            "name": filename,
            "data": data,
            "public": False,
            "trashed": False,
            "purged": False,
        }
        return UploadedFile(fid, f"https://drive.google.com/file/d/{fid}/view?usp=drivesdk")

    def share_public(self, file_id: str) -> None:
        if "share" in self.fail_on and self.share_applies_before_fail and file_id in self.files:
            self.files[file_id]["public"] = True
        self._check("share")
        self._get(file_id)["public"] = True

    def trash(self, file_id: str) -> None:
        self._check("trash")
        self._get(file_id)["trashed"] = True

    def untrash(self, file_id: str) -> None:
        self._check("untrash")
        self._get(file_id)["trashed"] = False

    # --- test helpers -----------------------------------------------------------

    def purge(self, file_id: str) -> None:
        """Simulate the file being deleted by hand, or the trash being emptied."""
        self.files[file_id]["purged"] = True

    def reachable(self, file_id: str) -> bool:
        f = self.files.get(file_id)
        return bool(f and f["public"] and not f["trashed"] and not f["purged"])
