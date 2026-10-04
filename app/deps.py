"""Request dependencies shared by every route: database, Drive, time zone, and auth.

`require_admin` is the single gate in front of every admin route and every /api/
route. It accepts either credential (spec section 10):

  * `Authorization: Bearer <ADMIN_TOKEN>` -- for scripts and curl;
  * the session cookie set by /admin/login -- for the app in the browser.

A cookie is sent by the browser automatically, even on requests another website
triggers. So cookie-authenticated requests that change anything must also carry an
Origin header naming this app. Bearer requests are exempt: another website cannot
make the browser attach an Authorization header.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import tzinfo
from typing import Annotated, Iterator

from fastapi import Depends, Header, HTTPException, Request

from app import db
from app.config import Settings, get_settings
from app.drive import DriveClient

SESSION_COOKIE = "qfs_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_conn(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[sqlite3.Connection]:
    conn = db.connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_drive(request: Request) -> DriveClient:
    return request.app.state.drive


def get_tz(request: Request) -> tzinfo | None:
    # None means the laptop's own zone. Tests set a fixed one on app.state.
    return getattr(request.app.state, "tz", None)


def same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    return bool(origin and host and origin == f"{request.url.scheme}://{host}")


def has_session(request: Request, conn: sqlite3.Connection) -> bool:
    return db.session_valid(conn, request.cookies.get(SESSION_COOKIE))


def require_admin(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if authorization is not None:
        # An Authorization header was sent: judge it alone, never fall back to the
        # cookie. A wrong token is a wrong token.
        supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if supplied and secrets.compare_digest(supplied, settings.admin_token):
            return
        raise HTTPException(status_code=401, detail="Unauthorized")

    if has_session(request, conn):
        if request.method not in SAFE_METHODS and not same_origin(request):
            raise HTTPException(status_code=403, detail="Cross-origin request refused")
        return

    raise HTTPException(status_code=401, detail="Unauthorized")


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Drive = Annotated[DriveClient, Depends(get_drive)]
Tz = Annotated[tzinfo | None, Depends(get_tz)]
Config = Annotated[Settings, Depends(get_settings)]
AdminOnly = Annotated[None, Depends(require_admin)]
