"""SQLite store: issued links, admin sessions, and settings.

Threading: connections are opened with check_same_thread=False because FastAPI runs
sync dependencies and sync route handlers on worker threads that need not be the
same one. This is safe only because (1) every request and every sweep run opens its
own connection -- none is shared -- and (2) each connection is used sequentially.
Preserve both invariants in any change. The library is in serialized mode
(sqlite3.threadsafety == 3).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.limits import to_iso, utcnow

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    drive_file_id TEXT NOT NULL UNIQUE,
    drive_url     TEXT NOT NULL,
    filename      TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    label         TEXT,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,   -- every QR has a limit: enforced here, not only in the UI
    revoked_at    TEXT,
    removed_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_links_due ON links(removed_at, expires_at);

CREATE TABLE IF NOT EXISTS admin_sessions (
    id_hash    TEXT PRIMARY KEY,   -- SHA-256 of the cookie value; the value itself is never stored
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# ------------------------------------------------------------------ connection


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _is_phase1_schema(db_path: Path) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(links)")}
    finally:
        conn.close()
    # Phase 1 keyed links by a public `token`; this schema has no such column.
    return "token" in cols


def init_db(db_path: Path) -> Path | None:
    """Create the schema. Returns the backup path if an old database was set aside.

    A phase-1 database cannot be migrated meaningfully -- its links pointed at the
    laptop, which no longer serves files. It is renamed, never deleted.
    """
    backup: Path | None = None
    if db_path.exists() and _is_phase1_schema(db_path):
        backup = db_path.with_name(db_path.name + ".phase1.bak")
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(db_path) + suffix)
            if src.exists():
                src.replace(Path(str(backup) + suffix))
        log.warning("Phase-1 database found; moved to %s", backup)

    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return backup


# ----------------------------------------------------------------------- links


def insert_link(
    conn: sqlite3.Connection,
    *,
    drive_file_id: str,
    drive_url: str,
    filename: str,
    size_bytes: int,
    sha256: str,
    label: str | None,
    expires_at: datetime,
) -> int:
    cur = conn.execute(
        """INSERT INTO links (drive_file_id, drive_url, filename, size_bytes, sha256,
                              label, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (drive_file_id, drive_url, filename, size_bytes, sha256, label,
         to_iso(utcnow()), to_iso(expires_at)),
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_link(conn: sqlite3.Connection, link_id: int) -> None:
    conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
    conn.commit()


def get_link(conn: sqlite3.Connection, link_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()


def list_links(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM links ORDER BY id DESC").fetchall()


def set_expiry(conn: sqlite3.Connection, link_id: int, expires_at: datetime) -> None:
    conn.execute(
        "UPDATE links SET expires_at = ? WHERE id = ?", (to_iso(expires_at), link_id)
    )
    conn.commit()


def mark_revoked(conn: sqlite3.Connection, link_id: int, when: datetime) -> None:
    conn.execute(
        "UPDATE links SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
        (to_iso(when), link_id),
    )
    conn.commit()


def mark_removed(conn: sqlite3.Connection, link_id: int, when: datetime) -> None:
    conn.execute(
        "UPDATE links SET removed_at = ? WHERE id = ? AND removed_at IS NULL",
        (to_iso(when), link_id),
    )
    conn.commit()


def mark_restored(conn: sqlite3.Connection, link_id: int, expires_at: datetime) -> None:
    conn.execute(
        "UPDATE links SET removed_at = NULL, expires_at = ? WHERE id = ?",
        (to_iso(expires_at), link_id),
    )
    conn.commit()


def due_for_removal(conn: sqlite3.Connection, now: datetime) -> list[sqlite3.Row]:
    """Links whose Drive file must go: past their limit, or ended but not yet trashed.

    The second case is how a failed "End now" (Drive unreachable at that moment) is
    retried until it succeeds.
    """
    return conn.execute(
        """SELECT * FROM links
            WHERE removed_at IS NULL
              AND (expires_at <= ? OR revoked_at IS NOT NULL)""",
        (to_iso(now),),
    ).fetchall()


# -------------------------------------------------------------------- settings


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


# -------------------------------------------------------------------- sessions


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_session(conn: sqlite3.Connection, hours: int) -> str:
    """Create a session and return the raw value for the cookie.

    Only its hash is stored, so a copy of the database does not contain a usable
    session.
    """
    raw = secrets.token_urlsafe(32)
    now = utcnow()
    conn.execute(
        "INSERT INTO admin_sessions (id_hash, created_at, expires_at) VALUES (?, ?, ?)",
        (_hash(raw), to_iso(now), to_iso(now + timedelta(hours=hours))),
    )
    conn.commit()
    return raw


def session_valid(conn: sqlite3.Connection, raw: str | None) -> bool:
    if not raw:
        return False
    row = conn.execute(
        "SELECT expires_at FROM admin_sessions WHERE id_hash = ?", (_hash(raw),)
    ).fetchone()
    return row is not None and row["expires_at"] > to_iso(utcnow())


def delete_session(conn: sqlite3.Connection, raw: str | None) -> None:
    if raw:
        conn.execute("DELETE FROM admin_sessions WHERE id_hash = ?", (_hash(raw),))
        conn.commit()


def purge_expired_sessions(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "DELETE FROM admin_sessions WHERE expires_at <= ?", (to_iso(utcnow()),)
    )
    conn.commit()
    return cur.rowcount
