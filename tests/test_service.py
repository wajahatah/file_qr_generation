"""Business rules: issuing, the orphan-safety rule, the sweep, change / end / reactivate.

The rule that matters most (spec 7.1): a file is never public on Drive without a row
in the database. A public file with no row has no limit anyone enforces -- a
permanent public link. Several tests below exist only to pin that down.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app import db, service
from app.drive import DriveError, DriveNotConnected
from app.limits import LimitError, expiry_instant, from_iso, last_day
from tests.conftest import TZ

NOW = datetime(2026, 9, 28, 7, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 28)
PDF = b"%PDF-1.4\n% test document\n" + b"x" * 500


def issue(conn, drive, *, day=None, label="Quotation 1", data=PDF):
    return service.issue_link(
        conn, drive, data=data, filename="q.pdf", label=label,
        last_day=day or TODAY + timedelta(days=7), tz=TZ,
    )


def file_of(conn, link_id):
    return db.get_link(conn, link_id)["drive_file_id"]


def set_last_day(conn, link_id, day):
    db.set_expiry(conn, link_id, expiry_instant(day, TZ))


# ------------------------------------------------------------------ validation


def test_validate_pdf_checks_the_bytes_not_the_name():
    service.validate_pdf(PDF, 10_000)
    with pytest.raises(service.NotAPdf):
        service.validate_pdf(b"MZ\x90\x00 windows executable", 10_000)
    with pytest.raises(service.IssueError):
        service.validate_pdf(b"", 10_000)
    with pytest.raises(service.UploadTooLarge):
        service.validate_pdf(PDF, 100)


# --------------------------------------------------------------------- issuing


def test_issue_uploads_records_and_shares(conn, drive):
    link_id = issue(conn, drive)
    row = db.get_link(conn, link_id)
    fid = row["drive_file_id"]
    assert drive.files[fid]["data"] == PDF
    assert drive.reachable(fid)
    assert row["drive_url"] == f"https://drive.google.com/file/d/{fid}/view?usp=drivesdk"
    assert last_day(from_iso(row["expires_at"]), TZ) == TODAY + timedelta(days=7)
    assert row["label"] == "Quotation 1"


def test_file_is_still_private_at_the_moment_its_row_is_written(conn, drive, monkeypatch):
    """The ordering itself: share happens strictly after the row is committed."""
    seen = {}
    real_insert = db.insert_link

    def spy(c, **kw):
        seen["public_when_recorded"] = drive.files[kw["drive_file_id"]]["public"]
        return real_insert(c, **kw)

    monkeypatch.setattr(db, "insert_link", spy)
    issue(conn, drive)
    assert seen["public_when_recorded"] is False


def test_not_connected_uploads_nothing(conn, drive):
    drive.connected = False
    with pytest.raises(DriveNotConnected):
        issue(conn, drive)
    assert drive.files == {} and db.list_links(conn) == []


def test_upload_failure_leaves_nothing_behind(conn, drive):
    drive.fail_on.add("upload")
    with pytest.raises(DriveError):
        issue(conn, drive)
    assert drive.files == {} and db.list_links(conn) == []


def test_database_failure_trashes_the_uploaded_file(conn, drive, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "insert_link", broken)
    with pytest.raises(RuntimeError):
        issue(conn, drive)
    (f,) = drive.files.values()
    assert f["public"] is False, "must never have been shared"
    assert f["trashed"] is True, "and must not be left cluttering their Drive"


def test_share_failure_is_cleaned_up_completely(conn, drive):
    drive.fail_on.add("share")
    with pytest.raises(DriveError):
        issue(conn, drive)
    (fid,) = drive.files
    assert not drive.reachable(fid)
    assert drive.files[fid]["trashed"]
    assert db.list_links(conn) == [], "cleaned up, so no trace is needed"


def test_share_that_took_effect_while_drive_went_away_is_still_removed_later(conn, drive):
    """The nasty case: Google applied the share but the reply was lost, and Drive is
    unreachable for the cleanup too. The file IS public. The row must survive as the
    record of what to remove, and the sweep must remove it once Drive is back."""
    drive.fail_on.update({"share", "trash"})
    drive.share_applies_before_fail = True
    with pytest.raises(DriveError):
        issue(conn, drive)
    (fid,) = drive.files
    assert drive.reachable(fid), "precondition: the file really is public"
    (row,) = db.list_links(conn)
    assert row["revoked_at"] is not None and row["removed_at"] is None

    drive.fail_on.clear()  # Drive comes back
    service.sweep(conn, drive, now=NOW)
    assert not drive.reachable(fid)
    assert db.get_link(conn, row["id"])["removed_at"] is not None


def test_every_link_has_a_limit_at_the_database_level(conn):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO links (drive_file_id, drive_url, filename, size_bytes, sha256, "
            "created_at, expires_at) VALUES ('x', 'u', 'f', 1, 's', 'now', NULL)"
        )


# ----------------------------------------------------------------------- sweep


def test_sweep_removes_exactly_the_expired_links(conn, drive):
    live = issue(conn, drive, day=TODAY + timedelta(days=3))
    today = issue(conn, drive, day=TODAY)
    expired = issue(conn, drive, day=TODAY)
    set_last_day(conn, expired, TODAY - timedelta(days=1))

    result = service.sweep(conn, drive, now=NOW)

    assert result.removed == 1
    assert not drive.reachable(file_of(conn, expired))
    assert db.get_link(conn, expired)["removed_at"] is not None
    for keep in (live, today):
        assert drive.reachable(file_of(conn, keep)), "a live link was removed"
        assert db.get_link(conn, keep)["removed_at"] is None


def test_sweep_is_idempotent(conn, drive):
    link = issue(conn, drive)
    set_last_day(conn, link, TODAY - timedelta(days=1))
    assert service.sweep(conn, drive, now=NOW).removed == 1
    assert service.sweep(conn, drive, now=NOW).removed == 0


def test_sweep_tolerates_a_file_deleted_by_hand(conn, drive):
    link = issue(conn, drive)
    set_last_day(conn, link, TODAY - timedelta(days=1))
    drive.purge(file_of(conn, link))
    result = service.sweep(conn, drive, now=NOW)
    assert result.already_gone == 1 and result.failed == 0
    assert db.get_link(conn, link)["removed_at"] is not None, "must not retry forever"


def test_sweep_failure_leaves_the_link_due_and_retries(conn, drive):
    link = issue(conn, drive)
    set_last_day(conn, link, TODAY - timedelta(days=1))
    drive.fail_on.add("trash")
    assert service.sweep(conn, drive, now=NOW).failed == 1
    assert db.get_link(conn, link)["removed_at"] is None, "not marked until Drive confirms"
    drive.fail_on.clear()
    assert service.sweep(conn, drive, now=NOW).removed == 1


def test_sweep_waits_when_drive_is_not_connected(conn, drive):
    link = issue(conn, drive)
    set_last_day(conn, link, TODAY - timedelta(days=1))
    drive.connected = False
    result = service.sweep(conn, drive, now=NOW)
    assert result.skipped_not_connected and result.removed == 0
    assert db.get_link(conn, link)["removed_at"] is None


# --------------------------------------------------------------- change limit


def test_extend_keeps_the_same_file_and_link(conn, drive):
    link = issue(conn, drive, day=TODAY + timedelta(days=7))
    before = db.get_link(conn, link)
    day = service.change_limit(conn, link, extend_days=7, now=NOW, tz=TZ)
    after = db.get_link(conn, link)
    assert day == TODAY + timedelta(days=14)
    assert (after["drive_file_id"], after["drive_url"]) == (before["drive_file_id"], before["drive_url"])


def test_shorten_to_an_earlier_date(conn, drive):
    link = issue(conn, drive, day=TODAY + timedelta(days=30))
    service.change_limit(conn, link, until=TODAY + timedelta(days=2), now=NOW, tz=TZ)
    assert last_day(from_iso(db.get_link(conn, link)["expires_at"]), TZ) == TODAY + timedelta(days=2)


def test_extending_rescues_a_link_that_is_past_its_limit_but_not_yet_removed(conn, drive):
    link = issue(conn, drive)
    set_last_day(conn, link, TODAY - timedelta(days=2))
    service.change_limit(conn, link, extend_days=7, now=NOW, tz=TZ)
    assert service.sweep(conn, drive, now=NOW).removed == 0
    assert drive.reachable(file_of(conn, link))


def test_change_refuses_past_dates(conn, drive):
    link = issue(conn, drive)
    with pytest.raises(LimitError):
        service.change_limit(conn, link, until=TODAY - timedelta(days=1), now=NOW, tz=TZ)


def test_change_refused_for_ended_and_removed_links(conn, drive):
    ended = issue(conn, drive)
    service.end_link(conn, drive, ended, now=NOW)
    with pytest.raises(service.IssueError, match="ended"):
        service.change_limit(conn, ended, extend_days=7, now=NOW, tz=TZ)

    gone = issue(conn, drive)
    set_last_day(conn, gone, TODAY - timedelta(days=1))
    service.sweep(conn, drive, now=NOW)
    with pytest.raises(service.IssueError, match="Reactivate"):
        service.change_limit(conn, gone, extend_days=7, now=NOW, tz=TZ)


def test_preview_and_save_agree(conn, drive):
    """What the user is shown before saving is exactly what gets stored."""
    link = issue(conn, drive, day=TODAY + timedelta(days=5))
    preview = service.resolve_change(db.get_link(conn, link), until=None, extend_days=30, now=NOW, tz=TZ)
    saved = service.change_limit(conn, link, extend_days=30, now=NOW, tz=TZ)
    assert preview == saved


# ------------------------------------------------------------------------ end


def test_end_now_removes_immediately(conn, drive):
    link = issue(conn, drive)
    assert service.end_link(conn, drive, link, now=NOW) is True
    row = db.get_link(conn, link)
    assert row["revoked_at"] and row["removed_at"]
    assert not drive.reachable(row["drive_file_id"])


def test_end_now_while_drive_is_unreachable_is_finished_by_the_sweep(conn, drive):
    link = issue(conn, drive)
    drive.fail_on.add("trash")
    assert service.end_link(conn, drive, link, now=NOW) is False
    assert drive.reachable(file_of(conn, link)), "honest: still reachable for now"
    assert db.get_link(conn, link)["revoked_at"] is not None
    drive.fail_on.clear()
    service.sweep(conn, drive, now=NOW)
    assert not drive.reachable(file_of(conn, link))


# ----------------------------------------------------------------- reactivate


def _expire_and_sweep(conn, drive, link, when=NOW):
    """Give the link a limit that had already run out by `when`, then sweep at `when`."""
    when_day = when.astimezone(TZ).date()
    set_last_day(conn, link, when_day - timedelta(days=1))
    service.sweep(conn, drive, now=when)
    assert db.get_link(conn, link)["removed_at"] is not None, "precondition: removed"


def test_reactivate_brings_back_the_same_link(conn, drive):
    link = issue(conn, drive)
    url = db.get_link(conn, link)["drive_url"]
    _expire_and_sweep(conn, drive, link)
    assert not drive.reachable(file_of(conn, link))

    service.reactivate(conn, drive, link, last_day=TODAY + timedelta(days=7), now=NOW, tz=TZ)

    row = db.get_link(conn, link)
    assert row["drive_url"] == url, "the QR already in the customer's hands must work again"
    assert drive.reachable(row["drive_file_id"])
    assert row["removed_at"] is None
    assert last_day(from_iso(row["expires_at"]), TZ) == TODAY + timedelta(days=7)


def test_reactivate_refused_for_ended_links(conn, drive):
    link = issue(conn, drive)
    service.end_link(conn, drive, link, now=NOW)
    with pytest.raises(service.IssueError, match="on purpose"):
        service.reactivate(conn, drive, link, last_day=TODAY + timedelta(days=7), now=NOW, tz=TZ)


def test_reactivate_refused_for_live_links(conn, drive):
    link = issue(conn, drive)
    with pytest.raises(service.IssueError, match="not expired"):
        service.reactivate(conn, drive, link, last_day=TODAY + timedelta(days=7), now=NOW, tz=TZ)


def test_reactivate_refused_after_30_days(conn, drive):
    link = issue(conn, drive)
    _expire_and_sweep(conn, drive, link, when=NOW - timedelta(days=31))
    with pytest.raises(service.IssueError, match="30 days"):
        service.reactivate(conn, drive, link, last_day=TODAY + timedelta(days=7), now=NOW, tz=TZ)


def test_reactivate_when_trash_was_emptied_by_hand(conn, drive):
    link = issue(conn, drive)
    _expire_and_sweep(conn, drive, link)
    drive.purge(file_of(conn, link))
    with pytest.raises(service.IssueError, match="no longer in the Google Drive trash"):
        service.reactivate(conn, drive, link, last_day=TODAY + timedelta(days=7), now=NOW, tz=TZ)
    assert db.get_link(conn, link)["removed_at"] is not None, "state unchanged on failure"
