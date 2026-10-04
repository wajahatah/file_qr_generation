"""Run the real app against the in-memory FakeDrive -- no Google account needed.

For trying the UI and for the full-system browser run. Not collected by pytest (the
file name does not start with test_), and nothing in app/ refers to it.

    .venv\\Scripts\\python.exe tests\\run_fake_server.py [port]

Admin token: fake-server-token. Data lives in a temporary folder and is discarded.
GET /__fake/drive shows what "Google Drive" holds, and whether each file is reachable
by someone scanning its QR code.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="qr-fake-"))
atexit.register(shutil.rmtree, _tmp, ignore_errors=True)
os.environ["DB_PATH"] = str(_tmp / "fake.db")
os.environ["ADMIN_TOKEN"] = "fake-server-token"
os.environ["GOOGLE_CLIENT_SECRET_FILE"] = str(_tmp / "unused.json")

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402
from tests.fakes import FakeDrive  # noqa: E402

drive = FakeDrive()
app.state.drive_override = drive


@app.get("/__fake/drive", include_in_schema=False)
def fake_drive_state():
    return {
        fid: {
            "name": f["name"],
            "bytes": len(f["data"]),
            "public": f["public"],
            "trashed": f["trashed"],
            "reachable_by_scanner": drive.reachable(fid),
        }
        for fid, f in drive.files.items()
    }


@app.get("/__fake/sample/{name}", include_in_schema=False)
def fake_sample(name: str):
    """Serves the sample PDFs so a browser test can feed one to the file input (a
    browser automation cannot operate the operating system's file picker)."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    path = (ROOT / "samples" / name).resolve()
    if path.parent != (ROOT / "samples").resolve() or not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="application/pdf")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Fake-Drive app on http://localhost:{port}/admin  (token: fake-server-token)", flush=True)
    print(f"Temporary data: {_tmp}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
