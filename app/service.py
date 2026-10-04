"""Issuing, changing, ending and reactivating links, and the removal sweep.

The one rule everything here protects (spec section 7.1): a file must never be public
on Drive without a row in the database. A public file with no row would have no limit
anyone enforces -- a permanent public link. So:

  * a file is shared only AFTER its row is committed;
  * when something fails after that, the row is kept as the record of what still has
    to be cleaned up, and the sweep retries until Drive confirms.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from app import db
from app.drive import DriveClient, DriveError, DriveNotConnected, DriveNotFound
from app.limits import (
    LimitError,
    can_reactivate,
    expiry_instant,
    extended_day,
    from_iso,
    utcnow,
    validate_day,
)

log = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"


class IssueError(ValueError):
    """The request cannot be carried out. The message is shown to the user."""


class UploadTooLarge(IssueError):
    """HTTP 413."""


class NotAPdf(IssueError):
    """HTTP 415."""


def _row_dt(row: sqlite3.Row, col: str) -> datetime | None:
    return from_iso(row[col]) if row[col] else None


# ------------------------------------------------------------------------ issue


def validate_pdf(data: bytes, max_bytes: int) -> None:
    if not data:
        raise IssueError("The file is empty.")
    if len(data) > max_bytes:
        raise UploadTooLarge(f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
    # Trust the bytes, not the file name.
    if not data.startswith(PDF_MAGIC):
        raise NotAPdf("Only PDF files can be shared.")


def issue_link(
    conn: sqlite3.Connection,
    drive: DriveClient,
    *,
    data: bytes,
    filename: str,
    label: str | None,
    last_day: date,
    tz: tzinfo | None = None,
) -> int:
    """Upload, record, then share. Returns the new link's id."""
    if not drive.is_connected():
        raise DriveNotConnected("Connect Google Drive first.")

    uploaded = drive.upload(data, filename)  # private until step 3

    try:
        link_id = db.insert_link(
            conn,
            drive_file_id=uploaded.id,
            drive_url=uploaded.url,
            filename=filename,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            label=label,
            expires_at=expiry_instant(last_day, tz),
        )
    except Exception:
        # Never shared, so not a leak -- but do not leave clutter in their Drive.
        _try_trash(drive, uploaded.id)
        raise

    try:
        drive.share_public(uploaded.id)
    except Exception:
        # The share may have succeeded at Google even though we saw an error (e.g. the
        # connection dropped after the request went out). Treat the file as possibly
        # public: record the intent to remove it, then try to remove it now.
        db.mark_revoked(conn, link_id, utcnow())
        if _try_trash(drive, uploaded.id):
            db.delete_link(conn, link_id)  # cleaned up: no trace needed
        # else: the revoked row stays, and the sweep retries until Drive confirms.
        raise

    return link_id


def _try_trash(drive: DriveClient, file_id: str) -> bool:
    try:
        drive.trash(file_id)
        return True
    except DriveNotFound:
        return True
    except DriveError as exc:
        log.error("Could not trash Drive file %s: %s", file_id, exc)
        return False


# ----------------------------------------------------------------- change limit


def _live_link(conn: sqlite3.Connection, link_id: int) -> sqlite3.Row:
    row = db.get_link(conn, link_id)
    if row is None:
        raise IssueError("That QR code does not exist.")
    if row["revoked_at"]:
        raise IssueError("This QR code was ended and cannot be changed. Issue a new one.")
    if row["removed_at"]:
        raise IssueError("This QR code has expired. Use Reactivate instead.")
    return row


def change_limit(
    conn: sqlite3.Connection,
    link_id: int,
    *,
    until: date | None = None,
    extend_days: int | None = None,
    now: datetime,
    tz: tzinfo | None = None,
) -> date:
    """Extend or shorten a live link. The same QR keeps working throughout."""
    row = _live_link(conn, link_id)
    day = resolve_change(row, until=until, extend_days=extend_days, now=now, tz=tz)
    db.set_expiry(conn, link_id, expiry_instant(day, tz))
    return day


def resolve_change(
    row: sqlite3.Row,
    *,
    until: date | None,
    extend_days: int | None,
    now: datetime,
    tz: tzinfo | None = None,
) -> date:
    """The new last day a change would produce. Shared by preview and save, so what
    the user is shown is exactly what gets stored."""
    if (until is None) == (extend_days is None):
        raise LimitError("Choose either a new date or a number of days to add.")
    if extend_days is not None:
        return extended_day(from_iso(row["expires_at"]), extend_days, now=now, tz=tz)
    return validate_day(until, now=now, tz=tz)  # type: ignore[arg-type]


def end_link(
    conn: sqlite3.Connection, drive: DriveClient, link_id: int, *, now: datetime
) -> bool:
    """End a link now. Returns True if Drive confirmed removal immediately.

    False means Drive was unreachable. The link is still recorded as ended and the
    sweep keeps retrying, so the customer loses access as soon as Drive is reachable.
    """
    row = db.get_link(conn, link_id)
    if row is None:
        raise IssueError("That QR code does not exist.")
    if row["revoked_at"] and row["removed_at"]:
        return True
    db.mark_revoked(conn, link_id, now)
    if row["removed_at"]:
        return True  # already gone from Drive (it had expired)
    if _try_trash(drive, row["drive_file_id"]):
        db.mark_removed(conn, link_id, now)
        return True
    return False


def reactivate(
    conn: sqlite3.Connection,
    drive: DriveClient,
    link_id: int,
    *,
    last_day: date,
    now: datetime,
    tz: tzinfo | None = None,
) -> None:
    """Bring an expired link back with a new limit. The same QR works again."""
    row = db.get_link(conn, link_id)
    if row is None:
        raise IssueError("That QR code does not exist.")
    if row["revoked_at"]:
        raise IssueError("This QR code was ended on purpose and cannot be reactivated.")
    if not row["removed_at"]:
        raise IssueError("This QR code has not expired. Change its limit instead.")
    if not can_reactivate(_row_dt(row, "removed_at"), None, now):
        raise IssueError(
            "This QR code expired more than 30 days ago. Google Drive has emptied it "
            "from the trash, so it cannot be restored. Issue a new one."
        )
    day = validate_day(last_day, now=now, tz=tz)
    try:
        drive.untrash(row["drive_file_id"])
    except DriveNotFound as exc:
        raise IssueError(
            "The file is no longer in the Google Drive trash (it may have been emptied "
            "by hand), so it cannot be restored. Issue a new QR code."
        ) from exc
    db.mark_restored(conn, link_id, expiry_instant(day, tz))


# ------------------------------------------------------------------------ sweep


@dataclass
class SweepResult:
    removed: int = 0
    already_gone: int = 0
    failed: int = 0
    skipped_not_connected: bool = False


def sweep(conn: sqlite3.Connection, drive: DriveClient, *, now: datetime) -> SweepResult:
    """Remove every file that is past its limit or was ended.

    Tolerates files already deleted by hand. Anything that fails stays due and is
    retried on the next run -- nothing is marked removed until Drive confirms it.
    """
    result = SweepResult()
    due = db.due_for_removal(conn, now)
    if not due:
        return result
    if not drive.is_connected():
        result.skipped_not_connected = True
        log.warning("%d link(s) are due for removal but Google Drive is not connected", len(due))
        return result
    for row in due:
        try:
            drive.trash(row["drive_file_id"])
            result.removed += 1
        except DriveNotFound:
            result.already_gone += 1
        except DriveNotConnected:
            result.skipped_not_connected = True
            log.warning("Google sign-in expired; removal sweep stopped")
            break
        except DriveError as exc:
            result.failed += 1
            log.warning("Could not remove link %s: %s", row["id"], exc)
            continue
        db.mark_removed(conn, row["id"], now)
    return result
