"""Time limits: presets, picked dates, day boundaries, and the words the user reads.

Everything here is a pure function, so the edge cases are exact rather than
approximate. The fixed "now" is Mon 28 Sep 2026, 10:00 in Riyadh (UTC+03:00).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import limits as L

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 28, 7, 0, tzinfo=timezone.utc)  # 10:00 local
TODAY = date(2026, 9, 28)


# ---------------------------------------------------------------- presets


@pytest.mark.parametrize("days", L.PRESET_DAYS)
def test_each_preset_counts_calendar_days_from_today(days):
    assert L.resolve_day(preset_days=days, now=NOW, tz=TZ) == TODAY + timedelta(days=days)


def test_presets_are_exactly_the_ones_in_the_spec():
    assert L.PRESET_DAYS == (1, 3, 7, 30)


@pytest.mark.parametrize("bad", [0, 2, 5, 14, 31, 365, -1])
def test_non_preset_day_counts_are_refused(bad):
    with pytest.raises(L.LimitError):
        L.resolve_day(preset_days=bad, now=NOW, tz=TZ)


def test_today_is_the_local_date_not_the_utc_date():
    """22:30 UTC on the 28th is already 01:30 on the 29th in Riyadh. "1 day" must mean
    until the 30th -- the user's calendar, not the server clock's."""
    late = datetime(2026, 9, 28, 22, 30, tzinfo=timezone.utc)
    assert L.local_today(late, TZ) == date(2026, 9, 29)
    assert L.resolve_day(preset_days=1, now=late, tz=TZ) == date(2026, 9, 30)


# ---------------------------------------------------------- picking a date


def test_picked_date_today_is_allowed():
    assert L.resolve_day(until=TODAY, now=NOW, tz=TZ) == TODAY


def test_picked_date_in_the_past_is_refused():
    with pytest.raises(L.LimitError, match="already passed"):
        L.resolve_day(until=TODAY - timedelta(days=1), now=NOW, tz=TZ)


def test_picked_date_up_to_one_year_ahead():
    assert L.resolve_day(until=TODAY + timedelta(days=365), now=NOW, tz=TZ)
    with pytest.raises(L.LimitError, match="one year"):
        L.resolve_day(until=TODAY + timedelta(days=366), now=NOW, tz=TZ)


@pytest.mark.parametrize("kwargs", [{}, {"preset_days": 7, "until": TODAY}])
def test_exactly_one_of_preset_or_date(kwargs):
    with pytest.raises(L.LimitError):
        L.resolve_day(now=NOW, tz=TZ, **kwargs)


# ------------------------------------------------------------ the boundary


def test_a_limit_runs_out_at_local_midnight_after_the_last_day():
    """Until Mon 5 Oct means all of 5 Oct: it runs out at 00:00 on the 6th, local."""
    instant = L.expiry_instant(date(2026, 10, 5), TZ)
    assert instant == datetime(2026, 10, 5, 21, 0, tzinfo=timezone.utc)  # 00:00 +03:00 on the 6th


def test_live_at_one_second_to_midnight_dead_at_midnight():
    instant = L.expiry_instant(date(2026, 10, 5), TZ)
    one_before = instant - timedelta(seconds=1)  # 23:59:59 local on the 5th
    kw = dict(expires_at=instant, revoked_at=None, removed_at=None, tz=TZ)
    assert L.describe(now=one_before, **kw).state == "expires_today"
    assert L.describe(now=instant, **kw).state == "expiring"


@pytest.mark.parametrize("offset", range(0, 400, 7))
def test_last_day_round_trips(offset):
    day = TODAY + timedelta(days=offset)
    assert L.last_day(L.expiry_instant(day, TZ), TZ) == day


def test_daylight_saving_change_is_handled():
    """UK clocks go back at 02:00 on Sun 25 Oct 2026. Midnight starting the 25th is
    still summer time (UTC+1); midnight starting the 26th is winter time (UTC+0).
    A fixed-offset shortcut would get one of these wrong by an hour."""
    uk = ZoneInfo("Europe/London")
    assert L.expiry_instant(date(2026, 10, 24), uk) == datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)
    assert L.expiry_instant(date(2026, 10, 25), uk) == datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)
    for d in (date(2026, 10, 24), date(2026, 10, 25), date(2026, 10, 26)):
        assert L.last_day(L.expiry_instant(d, uk), uk) == d


def test_system_local_zone_path_round_trips():
    """tz=None is what the running app uses: the laptop's own zone."""
    day = date(2026, 12, 31)
    assert L.last_day(L.expiry_instant(day)) == day


# ------------------------------------------------------------------- extend


def test_extend_counts_from_the_current_last_day():
    current = L.expiry_instant(date(2026, 10, 5), TZ)
    assert L.extended_day(current, 7, now=NOW, tz=TZ) == date(2026, 10, 12)


def test_extend_on_an_already_expired_link_counts_from_today():
    """+7 days on a link that ran out last week must give a real seven days."""
    ran_out = L.expiry_instant(date(2026, 9, 20), TZ)
    assert L.extended_day(ran_out, 7, now=NOW, tz=TZ) == TODAY + timedelta(days=7)


@pytest.mark.parametrize("bad", [1, 3, 14, 0])
def test_extend_only_by_the_offered_amounts(bad):
    with pytest.raises(L.LimitError):
        L.extended_day(L.expiry_instant(TODAY, TZ), bad, now=NOW, tz=TZ)


def test_extend_cannot_push_past_one_year():
    far = L.expiry_instant(TODAY + timedelta(days=360), TZ)
    with pytest.raises(L.LimitError, match="one year"):
        L.extended_day(far, 30, now=NOW, tz=TZ)


# ------------------------------------------------------------------ the words


@pytest.mark.parametrize(
    "day,expected",
    [
        (TODAY, "Customers can open this until Mon 28 Sep 2026, 11:59 PM (today only)"),
        (TODAY + timedelta(days=1), "Customers can open this until Tue 29 Sep 2026, 11:59 PM (1 day)"),
        (TODAY + timedelta(days=7), "Customers can open this until Mon 5 Oct 2026, 11:59 PM (7 days)"),
    ],
)
def test_limit_sentence(day, expected):
    assert L.limit_sentence(day, now=NOW, tz=TZ) == expected


def test_day_format_has_no_leading_zero():
    assert L.fmt_day(date(2026, 10, 5)) == "Mon 5 Oct"
    assert L.fmt_day(date(2026, 10, 5), with_year=True) == "Mon 5 Oct 2026"


def _status(last_day, *, revoked=None, removed=None, now=NOW):
    return L.describe(
        expires_at=L.expiry_instant(last_day, TZ),
        revoked_at=revoked,
        removed_at=removed,
        now=now,
        tz=TZ,
    )


def test_status_active_with_days_left():
    s = _status(TODAY + timedelta(days=7))
    assert (s.state, s.text) == ("active", "Active · until Mon 5 Oct (7 days left)")
    assert (s.can_change, s.can_end, s.can_reactivate) == (True, True, False)


def test_status_one_day_left_is_singular():
    assert _status(TODAY + timedelta(days=1)).text == "Active · until Tue 29 Sep (1 day left)"


def test_status_expires_today():
    s = _status(TODAY)
    assert (s.state, s.text) == ("expires_today", "Expires today at 11:59 PM")


def test_status_past_limit_but_not_yet_removed():
    """Laptop was off at the limit: the link still works until the app removes it,
    and the user must be able to see that and still extend or end it."""
    s = _status(TODAY - timedelta(days=2))
    assert (s.state, s.text) == ("expiring", "Expired — removing now")
    assert (s.can_change, s.can_end, s.can_reactivate) == (True, True, False)


def test_status_expired_and_removed_offers_reactivation_with_days_left():
    removed = NOW - timedelta(days=3)
    s = _status(TODAY - timedelta(days=4), removed=removed)
    assert s.state == "expired"
    assert s.text == "Expired · Thu 24 Sep — can be reactivated for 27 days more"
    assert s.can_reactivate and not s.can_change and not s.can_end


def test_reactivation_window_closes_after_30_days():
    removed = NOW - timedelta(days=30)
    s = _status(TODAY - timedelta(days=31), removed=removed)
    assert s.state == "expired" and not s.can_reactivate
    assert "reactivated" not in s.text
    assert L.can_reactivate(NOW - timedelta(days=29), None, NOW)
    assert not L.can_reactivate(NOW - timedelta(days=30), None, NOW)


def test_status_ended_is_final():
    s = _status(TODAY + timedelta(days=5), revoked=NOW - timedelta(hours=1))
    assert (s.state, s.text) == ("ended", "Ended · Mon 28 Sep")
    assert not (s.can_change or s.can_end or s.can_reactivate)
    assert not L.can_reactivate(NOW, NOW, NOW), "an ended link can never be reactivated"
