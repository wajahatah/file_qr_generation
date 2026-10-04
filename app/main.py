"""QR File Share: issue QR codes for PDFs delivered from Google Drive, with time limits.

The app runs on the user's laptop and listens on 127.0.0.1 only. QR codes point at
Google Drive, so they keep working while the laptop is off. The app enforces each
time limit by moving expired files to the Drive trash (spec section 5).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import db, service, timezone
from app.admin import router as admin_router
from app.config import get_settings
from app.deps import AdminOnly, Config, Conn, Drive, Tz
from app.drive import (
    DriveError,
    DriveNotConnected,
    DriveSetupError,
    GoogleDrive,
)
from app.limits import (
    DEFAULT_PRESET_DAYS,
    EXTEND_DAYS,
    MAX_DAYS_AHEAD,
    PRESET_DAYS,
    LimitError,
    describe,
    fmt_day,
    from_iso,
    last_day,
    limit_sentence,
    local_today,
    resolve_day,
    to_iso,
    utcnow,
)
from app.qr import make_qr_png
from app.tokens import build_token_store

log = logging.getLogger("qr_file_share")
HERE = Path(__file__).parent

DEFAULT_PRESET_KEY = "default_preset_days"

# No inline scripts or styles, no third-party origins, never framed.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; manifest-src 'self'; worker-src 'self'; object-src 'none'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


# ------------------------------------------------------------------ removal sweep


def run_sweep_once(app: FastAPI) -> dict[str, Any]:
    settings = get_settings()
    conn = db.connect(settings.db_path)
    try:
        db.purge_expired_sessions(conn)
        now = utcnow()
        result = service.sweep(conn, app.state.drive, now=now)
        pending = len(db.due_for_removal(conn, now))
    finally:
        conn.close()
    summary = {
        "at": to_iso(now),
        "removed": result.removed + result.already_gone,
        "failed": result.failed,
        "pending": pending,
        "drive_not_connected": result.skipped_not_connected,
    }
    app.state.last_sweep = summary
    if summary["removed"]:
        log.info("Removed %d expired link(s) from Google Drive", summary["removed"])
    return summary


async def _sweep_loop(app: FastAPI, interval_seconds: float) -> None:
    while True:
        try:
            await run_in_threadpool(run_sweep_once, app)
        except Exception:
            # Never let one bad run kill the loop; the next run retries everything.
            log.exception("Removal sweep failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Before anything reads the clock: the zone decides when each limit ends.
    app.state.zone = timezone.resolve(settings.tz, settings.host_windows_tz)
    timezone.apply(app.state.zone)
    backup = db.init_db(settings.db_path)
    if backup:
        log.warning("An old phase-1 database was set aside as %s", backup.name)
    app.state.drive = getattr(app.state, "drive_override", None) or GoogleDrive(
        settings.google_client_secret_file,
        token_store=build_token_store(settings),
        sign_in_port=settings.oauth_redirect_port,
        sign_in_bind=settings.oauth_bind_address,
        open_browser=settings.oauth_open_browser,
    )
    app.state.last_sweep = None
    # Runs immediately at startup -- that is what catches limits that ran out while
    # the laptop was off -- then every SWEEP_INTERVAL_MINUTES.
    task = asyncio.create_task(_sweep_loop(app, settings.sweep_interval_minutes * 60))
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(
    title="QR File Share",
    version="2.0.0",
    description="Issue QR codes for PDFs delivered from Google Drive, with time limits.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
app.include_router(admin_router)


# --------------------------------------------------------------------- middleware


def _host_only(header: str) -> str:
    h = header.strip().lower()
    if h.startswith("["):  # IPv6 literal, e.g. [::1]:8000
        return h[: h.find("]") + 1]
    return h.rsplit(":", 1)[0] if ":" in h else h


@app.middleware("http")
async def guard(request: Request, call_next):
    # DNS rebinding defence: a malicious site can point its own domain at 127.0.0.1,
    # but it cannot make the browser send Host: localhost.
    if _host_only(request.headers.get("host", "")) not in get_settings().allowed_hosts:
        return PlainTextResponse("Invalid host", status_code=400)

    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/admin"):
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Frame-Options", "DENY")
    if path.startswith("/api/") or path.startswith("/admin"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif path.startswith("/static/") or path == "/sw.js":
        # Revalidate on every load (an unchanged file is a tiny 304). Without this the
        # browser may keep an old admin.js / admin.css after the app is updated -- a new
        # page running old script. Found in the full-system browser run.
        response.headers.setdefault("Cache-Control", "no-cache")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # "same-origin", deliberately NOT "no-referrer": under no-referrer, browsers send
    # `Origin: null` on POSTs -- even to the page's own server -- and the CSRF check in
    # deps.require_admin rightly refuses null, which would break every save in the
    # app. same-origin still keeps the laptop's address from leaking to Google when a
    # Drive link is opened.
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


# ------------------------------------------------------------------ error mapping


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": message})


@app.exception_handler(LimitError)
async def _limit_error(_: Request, exc: LimitError):
    return _err(400, str(exc))


@app.exception_handler(service.IssueError)
async def _issue_error(_: Request, exc: service.IssueError):
    return _err(400, str(exc))


@app.exception_handler(service.UploadTooLarge)
async def _too_large(_: Request, exc: service.UploadTooLarge):
    return _err(413, str(exc))


@app.exception_handler(service.NotAPdf)
async def _not_pdf(_: Request, exc: service.NotAPdf):
    return _err(415, str(exc))


@app.exception_handler(DriveSetupError)
async def _setup_error(_: Request, exc: DriveSetupError):
    return _err(400, str(exc))


@app.exception_handler(DriveNotConnected)
async def _not_connected(_: Request, exc: DriveNotConnected):
    return _err(409, str(exc))


@app.exception_handler(DriveError)
async def _drive_error(_: Request, exc: DriveError):
    return _err(502, str(exc))


# --------------------------------------------------------------------- helpers


def _dt(row, col):
    return from_iso(row[col]) if row[col] else None


def link_json(row, *, tz) -> dict[str, Any]:
    now = utcnow()
    expires = from_iso(row["expires_at"])
    st = describe(
        expires_at=expires,
        revoked_at=_dt(row, "revoked_at"),
        removed_at=_dt(row, "removed_at"),
        now=now,
        tz=tz,
    )
    end = last_day(expires, tz)
    return {
        "id": row["id"],
        "label": row["label"],
        "filename": row["filename"],
        "size_bytes": row["size_bytes"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "last_day": end.isoformat(),
        "last_day_text": fmt_day(end, with_year=True),
        "drive_url": row["drive_url"],
        "status": {"state": st.state, "text": st.text},
        "actions": {
            "change": st.can_change,
            "end": st.can_end,
            "reactivate": st.can_reactivate,
        },
    }


def _default_preset(conn) -> int:
    raw = db.get_setting(conn, DEFAULT_PRESET_KEY)
    try:
        value = int(raw) if raw is not None else DEFAULT_PRESET_DAYS
    except ValueError:
        value = DEFAULT_PRESET_DAYS
    return value if value in PRESET_DAYS else DEFAULT_PRESET_DAYS


def _clean_filename(name: str | None) -> str:
    base = os.path.basename((name or "").replace("\\", "/")).strip() or "document.pdf"
    base = "".join(ch for ch in base if ch.isprintable())[:150]
    return base if base.lower().endswith(".pdf") else base + ".pdf"


def _get_row(conn, link_id: int):
    row = db.get_link(conn, link_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown QR code")
    return row


# ---------------------------------------------------------------------- routes


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def status(
    _: AdminOnly, conn: Conn, drive: Drive, tz: Tz, settings: Config, request: Request
) -> dict[str, Any]:
    now = utcnow()
    today = local_today(now, tz)
    conn_status = drive.status()
    return {
        "drive": {
            "state": conn_status.state,
            "email": conn_status.email,
            "message": conn_status.message,
            "sign_in_url": conn_status.sign_in_url,
        },
        "run_mode": settings.run_mode,
        # The page compares this offset with the browser's own -- the laptop's real
        # zone -- and warns if they differ (spec-docker 3.3).
        "time_zone": timezone.report(request.app.state.zone, now),
        "limits": {
            "presets": list(PRESET_DAYS),
            "extend": list(EXTEND_DAYS),
            "default_preset_days": _default_preset(conn),
            "today": today.isoformat(),
            "max_day": (today + timedelta(days=MAX_DAYS_AHEAD)).isoformat(),
        },
        "max_upload_bytes": settings.max_upload_bytes,
        "last_sweep": request.app.state.last_sweep,
    }


class LimitChoice(BaseModel):
    preset_days: int | None = None
    until: date | None = None


@app.post("/api/limits/preview")
def preview_limit(_: AdminOnly, body: LimitChoice, tz: Tz) -> dict[str, str]:
    """The sentence under the limit buttons. Server-side so the date logic lives in
    exactly one tested place, not duplicated in JavaScript."""
    now = utcnow()
    day = resolve_day(preset_days=body.preset_days, until=body.until, now=now, tz=tz)
    return {"last_day": day.isoformat(), "sentence": limit_sentence(day, now=now, tz=tz)}


@app.post("/api/drive/connect", status_code=202)
def drive_connect(_: AdminOnly, drive: Drive) -> dict[str, str]:
    drive.start_connect()
    return {"state": "connecting"}


@app.post("/api/drive/disconnect")
def drive_disconnect(_: AdminOnly, drive: Drive) -> dict[str, str]:
    drive.disconnect()
    return {"state": "disconnected"}


@app.post("/api/links", status_code=201)
def create_link(
    _: AdminOnly,
    conn: Conn,
    drive: Drive,
    settings: Config,
    tz: Tz,
    file: UploadFile,
    label: Annotated[str | None, Form()] = None,
    preset_days: Annotated[int | None, Form()] = None,
    until: Annotated[date | None, Form()] = None,
) -> dict[str, Any]:
    # Read at most one byte past the cap: enough to know it is too big without
    # pulling an arbitrarily large upload into memory.
    data = file.file.read(settings.max_upload_bytes + 1)
    service.validate_pdf(data, settings.max_upload_bytes)
    day = resolve_day(preset_days=preset_days, until=until, now=utcnow(), tz=tz)
    clean_label = (label or "").strip()[:200] or None
    link_id = service.issue_link(
        conn,
        drive,
        data=data,
        filename=_clean_filename(file.filename),
        label=clean_label,
        last_day=day,
        tz=tz,
    )
    return link_json(_get_row(conn, link_id), tz=tz)


@app.get("/api/links")
def list_links(_: AdminOnly, conn: Conn, tz: Tz) -> dict[str, Any]:
    return {"links": [link_json(r, tz=tz) for r in db.list_links(conn)]}


@app.get("/api/links/{link_id}")
def get_link(_: AdminOnly, link_id: int, conn: Conn, tz: Tz) -> dict[str, Any]:
    return link_json(_get_row(conn, link_id), tz=tz)


@app.get("/api/links/{link_id}/qr.png")
def link_qr(_: AdminOnly, link_id: int, conn: Conn) -> Response:
    row = _get_row(conn, link_id)
    return Response(content=make_qr_png(row["drive_url"]), media_type="image/png")


class LimitChange(BaseModel):
    until: date | None = None
    extend_days: int | None = None


@app.post("/api/links/{link_id}/limit/preview")
def preview_change(
    _: AdminOnly, link_id: int, body: LimitChange, conn: Conn, tz: Tz
) -> dict[str, str]:
    row = _get_row(conn, link_id)
    now = utcnow()
    day = service.resolve_change(row, until=body.until, extend_days=body.extend_days, now=now, tz=tz)
    return {"last_day": day.isoformat(), "sentence": limit_sentence(day, now=now, tz=tz)}


@app.post("/api/links/{link_id}/limit")
def change_limit(
    _: AdminOnly, link_id: int, body: LimitChange, conn: Conn, tz: Tz
) -> dict[str, Any]:
    _get_row(conn, link_id)
    service.change_limit(
        conn, link_id, until=body.until, extend_days=body.extend_days, now=utcnow(), tz=tz
    )
    return link_json(_get_row(conn, link_id), tz=tz)


@app.post("/api/links/{link_id}/end")
def end_link(_: AdminOnly, link_id: int, conn: Conn, drive: Drive, tz: Tz) -> dict[str, Any]:
    _get_row(conn, link_id)
    confirmed = service.end_link(conn, drive, link_id, now=utcnow())
    out = link_json(_get_row(conn, link_id), tz=tz)
    out["removed_from_drive"] = confirmed
    return out


@app.post("/api/links/{link_id}/reactivate")
def reactivate_link(
    _: AdminOnly, link_id: int, body: LimitChoice, conn: Conn, drive: Drive, tz: Tz
) -> dict[str, Any]:
    _get_row(conn, link_id)
    now = utcnow()
    day = resolve_day(preset_days=body.preset_days, until=body.until, now=now, tz=tz)
    service.reactivate(conn, drive, link_id, last_day=day, now=now, tz=tz)
    return link_json(_get_row(conn, link_id), tz=tz)


class SettingsBody(BaseModel):
    default_preset_days: int


@app.get("/api/settings")
def get_app_settings(_: AdminOnly, conn: Conn) -> dict[str, int]:
    return {"default_preset_days": _default_preset(conn)}


@app.put("/api/settings")
def put_app_settings(_: AdminOnly, body: SettingsBody, conn: Conn) -> dict[str, int]:
    if body.default_preset_days not in PRESET_DAYS:
        raise LimitError(
            f"The default must be one of {', '.join(str(d) for d in PRESET_DAYS)} days."
        )
    db.set_setting(conn, DEFAULT_PRESET_KEY, str(body.default_preset_days))
    return {"default_preset_days": body.default_preset_days}


@app.post("/api/maintenance/sweep")
def sweep_now(_: AdminOnly, request: Request) -> dict[str, Any]:
    return run_sweep_once(request.app)
