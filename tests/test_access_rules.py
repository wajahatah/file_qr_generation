"""Access rules at the data layer: expiry, download caps, revocation, and the race.

These are unit tests against app.db, deliberately below the HTTP layer, because this
is where the correctness actually lives -- the route is a thin wrapper.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from app import db
from tests.conftest import make_link


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


# ------------------------------------------------------------------ classification


def test_unknown_token_classifies_as_not_found() -> None:
    assert db.classify(None) == db.OUTCOME_NOT_FOUND


def test_link_with_no_constraints_is_servable(conn) -> None:
    token = make_link(conn)
    assert db.classify(db.get_link(conn, token)) == db.OUTCOME_SERVED


# ------------------------------------------------------------------------- expiry


@pytest.mark.parametrize(
    "offset_seconds,expected",
    [
        (60, db.OUTCOME_SERVED),  # expires in a minute -> still fine
        (1, db.OUTCOME_SERVED),  # T-1s -> the last servable instant
        (0, db.OUTCOME_EXPIRED),  # T exactly -> expired (boundary is inclusive)
        (-1, db.OUTCOME_EXPIRED),  # T+1s
        (-86400, db.OUTCOME_EXPIRED),
    ],
)
def test_expiry_boundaries(conn, offset_seconds: int, expected: str) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires = now + timedelta(seconds=offset_seconds)
    token = make_link(conn, expires_at=iso(expires))
    assert db.classify(db.get_link(conn, token), at=iso(now)) == expected


def test_expired_link_cannot_be_consumed(conn) -> None:
    past = datetime.now(timezone.utc) - timedelta(days=1)
    token = make_link(conn, expires_at=iso(past))
    assert db.try_consume_download(conn, token) is False
    assert db.get_link(conn, token)["download_count"] == 0


def test_null_expiry_never_expires(conn) -> None:
    token = make_link(conn, expires_at=None)
    assert db.try_consume_download(conn, token) is True


def test_iso_in_days_produces_a_future_utc_timestamp() -> None:
    stamp = db.iso_in_days(30)
    assert stamp is not None
    assert stamp > db.now_iso()
    assert db.iso_in_days(None) is None


# --------------------------------------------------------------------- download cap


def test_nth_download_succeeds_and_n_plus_one_fails(conn) -> None:
    token = make_link(conn, max_downloads=3)
    assert [db.try_consume_download(conn, token) for _ in range(3)] == [True] * 3
    assert db.try_consume_download(conn, token) is False
    assert db.get_link(conn, token)["download_count"] == 3
    assert db.classify(db.get_link(conn, token)) == db.OUTCOME_EXHAUSTED


def test_unlimited_downloads_when_cap_is_null(conn) -> None:
    token = make_link(conn, max_downloads=None)
    for _ in range(50):
        assert db.try_consume_download(conn, token) is True


def test_counter_does_not_advance_past_the_cap(conn) -> None:
    """A rejected attempt must not increment the counter."""
    token = make_link(conn, max_downloads=1)
    db.try_consume_download(conn, token)
    for _ in range(5):
        db.try_consume_download(conn, token)
    assert db.get_link(conn, token)["download_count"] == 1


# --------------------------------------------------------------------- revocation


def test_revocation_takes_effect_immediately(conn) -> None:
    token = make_link(conn)
    assert db.try_consume_download(conn, token) is True
    assert db.revoke(conn, token) is True
    assert db.try_consume_download(conn, token) is False
    assert db.classify(db.get_link(conn, token)) == db.OUTCOME_REVOKED


def test_revoking_twice_is_reported_as_no_change(conn) -> None:
    token = make_link(conn)
    assert db.revoke(conn, token) is True
    assert db.revoke(conn, token) is False  # idempotent, but reports it was already done


def test_revocation_beats_an_otherwise_valid_link(conn) -> None:
    future = datetime.now(timezone.utc) + timedelta(days=365)
    token = make_link(conn, expires_at=iso(future), max_downloads=100)
    db.revoke(conn, token)
    assert db.classify(db.get_link(conn, token)) == db.OUTCOME_REVOKED


# --------------------------------------------------------------------------- race


def test_concurrent_downloads_respect_a_cap_of_one(env) -> None:
    """Twenty simultaneous scans of a single-use link: exactly one may win.

    This is the test that justifies `try_consume_download` being one conditional
    UPDATE. A read-then-write implementation passes every other test in this file
    and fails this one.
    """
    db.init_db(env.db_path)
    setup = db.connect(env.db_path)
    token = make_link(setup, max_downloads=1)
    setup.close()

    def attempt() -> bool:
        # A fresh connection per thread, mirroring one connection per request.
        c = db.connect(env.db_path)
        try:
            return db.try_consume_download(c, token)
        finally:
            c.close()

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: attempt(), range(20)))

    assert sum(results) == 1, f"expected exactly 1 winner, got {sum(results)}"

    check = db.connect(env.db_path)
    assert check.execute(
        "SELECT download_count FROM links WHERE token = ?", (token,)
    ).fetchone()[0] == 1
    check.close()


def test_concurrent_downloads_respect_a_cap_of_five(env) -> None:
    db.init_db(env.db_path)
    setup = db.connect(env.db_path)
    token = make_link(setup, max_downloads=5)
    setup.close()

    def attempt() -> bool:
        c = db.connect(env.db_path)
        try:
            return db.try_consume_download(c, token)
        finally:
            c.close()

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: attempt(), range(20)))

    assert sum(results) == 5


# ------------------------------------------------------------------------ log purge


def test_purge_removes_only_logs_older_than_retention(conn) -> None:
    token = make_link(conn)
    db.log_access(conn, token=token, ip=None, user_agent=None, outcome=db.OUTCOME_SERVED)
    old = iso(datetime.now(timezone.utc) - timedelta(days=200))
    conn.execute(
        "INSERT INTO access_log (token, accessed_at, ip, user_agent, outcome)"
        " VALUES (?, ?, ?, ?, ?)",
        (token, old, None, None, db.OUTCOME_SERVED),
    )
    conn.commit()

    assert len(db.access_log_for(conn, token)) == 2
    assert db.purge_old_logs(conn, retention_days=90) == 1
    assert len(db.access_log_for(conn, token)) == 1
