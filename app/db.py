"""SQLite metadata store: the token -> file mapping and the access log.

Concurrency note: the download counter is incremented by a single conditional UPDATE
(`try_consume_download`) rather than a read-then-write. With `max_downloads = 1` and
two simultaneous scans, a read-then-write would let both through; the conditional
UPDATE lets exactly one win, because SQLite serialises writers.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

# Outcomes recorded in access_log. Only "served" returns a file; every other value
# produces an identical 404 to the visitor (see app/main.py).
OUTCOME_SERVED = "served"
OUTCOME_EXPIRED = "expired"
OUTCOME_REVOKED = "revoked"
OUTCOME_EXHAUSTED = "exhausted"
OUTCOME_NOT_FOUND = "not_found"

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    token          TEXT PRIMARY KEY,
    storage_ref    TEXT NOT NULL,
    filename       TEXT NOT NULL,
    content_type   TEXT NOT NULL DEFAULT 'application/pdf',
    size_bytes     INTEGER NOT NULL,
    sha256         TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    expires_at     TEXT,
    max_downloads  INTEGER,
    download_count INTEGER NOT NULL DEFAULT 0,
    revoked_at     TEXT,
    label          TEXT
);

CREATE TABLE IF NOT EXISTS access_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT NOT NULL,
    accessed_at TEXT NOT NULL,
    ip          TEXT,
    user_agent  TEXT,
    outcome     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_access_log_token ON access_log(token);
CREATE INDEX IF NOT EXISTS idx_access_log_time  ON access_log(accessed_at);
"""


def now_iso() -> str:
    """Current UTC time, ISO-8601, second precision. All stored times use this."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def iso_in_days(days: int | None) -> str | None:
    if days is None:
        return None
    return (
        (datetime.now(timezone.utc) + timedelta(days=days))
        .replace(microsecond=0)
        .isoformat()
    )


def new_token() -> str:
    """128 bits of entropy, URL-safe, ~22 characters."""
    return secrets.token_urlsafe(16)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False is required, not a shortcut: FastAPI runs sync generator
    # dependencies (get_conn) in a worker thread while `async def` routes run on the
    # event loop, so the connection is legitimately created and used from different
    # threads. This is safe here only because of two invariants, which must hold for
    # any future change to the request path:
    #   1. one connection per request -- connections are never shared between requests;
    #   2. accesses within a request are strictly sequential, never concurrent.
    # The underlying library is in serialized mode (sqlite3.threadsafety == 3).
    conn = sqlite3.connect(db_path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL lets readers proceed while a writer holds the lock; busy_timeout absorbs
    # the brief contention when two scans land together.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def create_link(
    conn: sqlite3.Connection,
    *,
    storage_ref: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
    expires_at: str | None,
    max_downloads: int | None,
    label: str | None,
) -> str:
    token = new_token()
    conn.execute(
        """INSERT INTO links (token, storage_ref, filename, content_type, size_bytes,
                              sha256, created_at, expires_at, max_downloads, label)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            token,
            storage_ref,
            filename,
            content_type,
            size_bytes,
            sha256,
            now_iso(),
            expires_at,
            max_downloads,
            label,
        ),
    )
    conn.commit()
    return token


def get_link(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM links WHERE token = ?", (token,)).fetchone()


def classify(row: sqlite3.Row | None, *, at: str | None = None) -> str:
    """Decide the outcome for a link WITHOUT mutating it.

    Used for logging the true reason and for the read-only metadata endpoint. The
    actual serve path must still call `try_consume_download`, which re-checks the
    same conditions atomically.
    """
    if row is None:
        return OUTCOME_NOT_FOUND
    now = at or now_iso()
    if row["revoked_at"] is not None:
        return OUTCOME_REVOKED
    # Lexicographic comparison is correct here: all timestamps are stored as
    # fixed-format UTC ISO-8601 strings.
    if row["expires_at"] is not None and row["expires_at"] <= now:
        return OUTCOME_EXPIRED
    if row["max_downloads"] is not None and row["download_count"] >= row["max_downloads"]:
        return OUTCOME_EXHAUSTED
    return OUTCOME_SERVED


def try_consume_download(conn: sqlite3.Connection, token: str) -> bool:
    """Atomically claim one download. Returns False if the link is not serveable.

    This is the single source of truth for "may this scan be served"; `classify` is
    only advisory.
    """
    cur = conn.execute(
        """UPDATE links
              SET download_count = download_count + 1
            WHERE token = ?
              AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > ?)
              AND (max_downloads IS NULL OR download_count < max_downloads)""",
        (token, now_iso()),
    )
    conn.commit()
    return cur.rowcount == 1


def revoke(conn: sqlite3.Connection, token: str) -> bool:
    cur = conn.execute(
        "UPDATE links SET revoked_at = ? WHERE token = ? AND revoked_at IS NULL",
        (now_iso(), token),
    )
    conn.commit()
    return cur.rowcount == 1


def log_access(
    conn: sqlite3.Connection,
    *,
    token: str,
    ip: str | None,
    user_agent: str | None,
    outcome: str,
) -> None:
    conn.execute(
        """INSERT INTO access_log (token, accessed_at, ip, user_agent, outcome)
           VALUES (?, ?, ?, ?, ?)""",
        (token, now_iso(), ip, user_agent, outcome),
    )
    conn.commit()


def access_log_for(conn: sqlite3.Connection, token: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM access_log WHERE token = ? ORDER BY id DESC", (token,)
    ).fetchall()
    return [dict(r) for r in rows]


def purge_old_logs(conn: sqlite3.Connection, retention_days: int) -> int:
    cutoff = (
        (datetime.now(timezone.utc) - timedelta(days=retention_days))
        .replace(microsecond=0)
        .isoformat()
    )
    cur = conn.execute("DELETE FROM access_log WHERE accessed_at < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def iter_links(conn: sqlite3.Connection) -> Iterator[sqlite3.Row]:
    yield from conn.execute("SELECT * FROM links ORDER BY created_at DESC")
