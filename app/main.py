"""FastAPI application: QR-based file delivery.

Route shape:
  /d/{token}   PUBLIC  -- the URL a QR code encodes. Validates, logs, streams.
  /api/...     ADMIN   -- bearer-token guarded upload and management.

Security posture for /d/{token}: every failure mode (unknown token, expired, revoked,
download cap exhausted) returns an identical 404 page. The true reason is written to
access_log only. Distinguishable errors would let a holder of one leaked QR probe for
which other tokens exist.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Iterator

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import db
from app.config import Settings, get_settings
from app.qr import download_url, make_qr_png
from app.storage import Storage, StorageError, build_storage

PDF_MAGIC = b"%PDF-"

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_storage: Storage | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _storage
    settings = get_settings()
    db.init_db(settings.db_path)
    _storage = build_storage(settings)
    yield
    _storage = None


app = FastAPI(
    title="QR File Share",
    version="1.0.0",
    description=(
        "Generate a QR code that delivers a document, with expiry, download caps, "
        "revocation and an access log."
    ),
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- deps


def get_conn(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[sqlite3.Connection]:
    conn = db.connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_storage(settings: Annotated[Settings, Depends(get_settings)]) -> Storage:
    # _storage is populated by the lifespan handler; fall back for direct unit use.
    return _storage if _storage is not None else build_storage(settings)


def require_admin(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    # compare_digest keeps the check constant-time against token guessing.
    if not secrets.compare_digest(supplied, settings.admin_token):
        raise HTTPException(status_code=401, detail="Unauthorized")


AdminOnly = Annotated[None, Depends(require_admin)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Config = Annotated[Settings, Depends(get_settings)]


# ------------------------------------------------------------------------ helpers


def client_fingerprint(request: Request) -> str | None:
    """Truncate the caller IP before it is stored.

    The full IP of a customer opening a quotation is personal data we do not need.
    A /24 (or /64 for IPv6) is enough to notice "this leaked QR is being hit from
    somewhere unexpected" without retaining an identifier for an individual.
    """
    raw = request.client.host if request.client else None
    if not raw:
        return None
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return None
    prefix = 24 if addr.version == 4 else 64
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))


def link_public_dict(row: sqlite3.Row, settings: Settings) -> dict[str, Any]:
    d = dict(row)
    d.pop("storage_ref", None)  # internal; never exposed
    d["url"] = download_url(settings.base_url, row["token"])
    d["status"] = db.classify(row)
    return d


def not_available() -> HTMLResponse:
    """The single response every /d/ failure produces."""
    body = templates.get_template("unavailable.html").render()
    return HTMLResponse(content=body, status_code=404)


# ------------------------------------------------------------------------- public


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/d/{token}")
def download(
    token: str,
    request: Request,
    conn: Conn,
    settings: Config,
    storage: Annotated[Storage, Depends(get_storage)],
):
    ip = client_fingerprint(request)
    ua = request.headers.get("user-agent")
    row = db.get_link(conn, token)

    # Determine the true reason for the log...
    outcome = db.classify(row)
    if outcome != db.OUTCOME_SERVED:
        db.log_access(conn, token=token, ip=ip, user_agent=ua, outcome=outcome)
        return not_available()

    # ...then claim the download atomically. If this loses a race against a
    # simultaneous scan on a capped link, classify() was already stale.
    if not db.try_consume_download(conn, token):
        db.log_access(
            conn, token=token, ip=ip, user_agent=ua, outcome=db.OUTCOME_EXHAUSTED
        )
        return not_available()

    try:
        stream = storage.open_stream(row["storage_ref"])
    except StorageError:
        # The metadata row exists but the blob is gone. Do not leak that distinction
        # to the visitor, but make it loud in the log.
        db.log_access(
            conn, token=token, ip=ip, user_agent=ua, outcome=db.OUTCOME_NOT_FOUND
        )
        return not_available()

    db.log_access(conn, token=token, ip=ip, user_agent=ua, outcome=db.OUTCOME_SERVED)
    filename = row["filename"].replace('"', "")
    return StreamingResponse(
        stream,
        media_type=row["content_type"],
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Content-Length": str(row["size_bytes"]),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# -------------------------------------------------------------------------- admin


@app.post("/api/files", status_code=201)
async def upload_file(
    _: AdminOnly,
    conn: Conn,
    settings: Config,
    storage: Annotated[Storage, Depends(get_storage)],
    file: UploadFile,
    expires_in_days: Annotated[int | None, Form()] = None,
    max_downloads: Annotated[int | None, Form()] = None,
    label: Annotated[str | None, Form()] = None,
    no_expiry: Annotated[bool, Form()] = False,
) -> JSONResponse:
    data = await file.read()

    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413, detail=f"File exceeds {settings.max_upload_bytes} bytes"
        )
    # Trust the bytes, not the extension or the declared content type.
    if not data.startswith(PDF_MAGIC):
        raise HTTPException(status_code=415, detail="Only PDF files are accepted")
    if max_downloads is not None and max_downloads < 1:
        raise HTTPException(status_code=400, detail="max_downloads must be >= 1")
    if expires_in_days is not None and expires_in_days < 1:
        raise HTTPException(status_code=400, detail="expires_in_days must be >= 1")

    if no_expiry:
        expires_at = None
    else:
        days = (
            expires_in_days
            if expires_in_days is not None
            else settings.default_expiry_days
        )
        expires_at = db.iso_in_days(days)

    filename = file.filename or "document.pdf"
    storage_ref = storage.save(
        data, filename=filename, content_type="application/pdf"
    )
    token = db.create_link(
        conn,
        storage_ref=storage_ref,
        filename=filename,
        content_type="application/pdf",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        expires_at=expires_at,
        max_downloads=max_downloads,
        label=label,
    )

    url = download_url(settings.base_url, token)
    png = make_qr_png(url)
    return JSONResponse(
        status_code=201,
        content={
            "token": token,
            "url": url,
            "filename": filename,
            "expires_at": expires_at,
            "max_downloads": max_downloads,
            "qr_png_base64": base64.b64encode(png).decode("ascii"),
        },
    )


@app.get("/api/files")
def list_files(_: AdminOnly, conn: Conn, settings: Config) -> dict[str, Any]:
    return {"links": [link_public_dict(r, settings) for r in db.iter_links(conn)]}


@app.get("/api/files/{token}")
def file_metadata(
    _: AdminOnly, token: str, conn: Conn, settings: Config
) -> dict[str, Any]:
    row = db.get_link(conn, token)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown token")
    return link_public_dict(row, settings)


@app.get("/api/files/{token}/qr.png")
def file_qr(_: AdminOnly, token: str, conn: Conn, settings: Config) -> Response:
    row = db.get_link(conn, token)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown token")
    png = make_qr_png(download_url(settings.base_url, token))
    return Response(content=png, media_type="image/png")


@app.post("/api/files/{token}/revoke")
def revoke_file(_: AdminOnly, token: str, conn: Conn) -> dict[str, Any]:
    row = db.get_link(conn, token)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown token")
    changed = db.revoke(conn, token)
    return {"token": token, "revoked": True, "already_revoked": not changed}


@app.get("/api/files/{token}/log")
def file_log(_: AdminOnly, token: str, conn: Conn) -> dict[str, Any]:
    row = db.get_link(conn, token)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown token")
    entries = db.access_log_for(conn, token)
    served = sum(1 for e in entries if e["outcome"] == db.OUTCOME_SERVED)
    return {
        "token": token,
        "served": served,
        "attempts": len(entries),
        "entries": entries,
    }


@app.post("/api/maintenance/purge-logs")
def purge_logs(_: AdminOnly, conn: Conn, settings: Config) -> dict[str, int]:
    deleted = db.purge_old_logs(conn, settings.log_retention_days)
    return {"deleted": deleted}
