"""The app's pages: login, the main screen, and the print view."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app import db
from app.deps import SESSION_COOKIE, Config, Conn, Tz, has_session, same_origin
from app.limits import describe, fmt_day, from_iso, last_day, utcnow

HERE = Path(__file__).parent
# Jinja autoescapes .html templates, so labels and filenames cannot inject markup.
templates = Jinja2Templates(directory=str(HERE / "templates"))

router = APIRouter()


def _to_login() -> RedirectResponse:
    return RedirectResponse("/admin/login", status_code=303)


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/admin", status_code=303)


@router.get("/admin", include_in_schema=False)
def app_page(request: Request, conn: Conn) -> Response:
    if not has_session(request, conn):
        return _to_login()
    return templates.TemplateResponse(request, "admin.html")


@router.get("/admin/login", include_in_schema=False)
def login_page(request: Request, conn: Conn) -> Response:
    if has_session(request, conn):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/admin/login", include_in_schema=False)
def login(
    request: Request,
    conn: Conn,
    settings: Config,
    token: Annotated[str, Form()] = "",
) -> Response:
    # Refuse a login submitted from another website (login CSRF). Browsers always send
    # Origin on a form POST; if it is present it must be ours.
    if request.headers.get("origin") is not None and not same_origin(request):
        raise HTTPException(status_code=403, detail="Cross-origin request refused")

    if not token or not secrets.compare_digest(token.strip(), settings.admin_token):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "That token is not right. It is in the .env file, and shown when start.cmd starts."},
            status_code=401,
        )

    raw = db.create_session(conn, settings.admin_session_hours)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        raw,
        max_age=settings.admin_session_hours * 3600,
        httponly=True,  # page scripts cannot read it
        samesite="strict",  # never sent on requests started by another website
        # Only when actually on HTTPS: over plain http a Secure cookie is silently
        # never sent, and login would appear to do nothing.
        secure=request.url.scheme == "https",
        path="/",
    )
    return resp


@router.post("/admin/logout", include_in_schema=False)
def logout(request: Request, conn: Conn) -> Response:
    if has_session(request, conn) and not same_origin(request):
        raise HTTPException(status_code=403, detail="Cross-origin request refused")
    db.delete_session(conn, request.cookies.get(SESSION_COOKIE))
    resp = _to_login()
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/admin/print/{link_id}", include_in_schema=False)
def print_page(request: Request, link_id: int, conn: Conn, tz: Tz) -> Response:
    if not has_session(request, conn):
        return _to_login()
    row = db.get_link(conn, link_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown QR code")
    expires = from_iso(row["expires_at"])
    status = describe(
        expires_at=expires,
        revoked_at=from_iso(row["revoked_at"]) if row["revoked_at"] else None,
        removed_at=from_iso(row["removed_at"]) if row["removed_at"] else None,
        now=utcnow(),
        tz=tz,
    )
    return templates.TemplateResponse(
        request,
        "print.html",
        {
            "link_id": link_id,
            "label": row["label"] or row["filename"],
            "until": fmt_day(last_day(expires, tz), with_year=True),
            "live": status.state in ("active", "expires_today"),
        },
    )


@router.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    # Served from the root so its scope covers the whole app, which is what lets
    # Edge and Chrome offer "Install app".
    return FileResponse(HERE / "static" / "sw.js", media_type="application/javascript")
