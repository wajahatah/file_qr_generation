"""Which time zone time limits use (app/timezone.py; spec-docker 3.3)."""

from __future__ import annotations

import time
from datetime import datetime, timezone as dt_timezone

import pytest

from app import timezone as Z


@pytest.mark.parametrize(
    "windows,iana",
    [
        ("Pakistan Standard Time", "Asia/Karachi"),
        ("Arab Standard Time", "Asia/Riyadh"),
        # Similar name, different place: must NOT become Riyadh.
        ("Arabian Standard Time", "Asia/Dubai"),
        ("GMT Standard Time", "Europe/London"),
    ],
)
def test_windows_zone_names_translate_to_iana(windows, iana):
    assert Z.windows_to_iana(windows) == iana


def test_explicit_tz_wins_over_the_laptop():
    assert Z.resolve("Asia/Riyadh", "Pakistan Standard Time") == Z.ZoneChoice("Asia/Riyadh", "env")


def test_laptop_zone_is_used_when_tz_is_not_set():
    assert Z.resolve(None, "Pakistan Standard Time") == Z.ZoneChoice("Asia/Karachi", "laptop")
    assert Z.resolve("", "Arab Standard Time") == Z.ZoneChoice("Asia/Riyadh", "laptop")
    assert Z.resolve("   ", "Arab Standard Time") == Z.ZoneChoice("Asia/Riyadh", "laptop")


def test_travelling_needs_no_rebuild():
    """The user's case: same image, laptop moved from Karachi to Riyadh."""
    assert Z.resolve(None, "Pakistan Standard Time").name == "Asia/Karachi"
    assert Z.resolve(None, "Arab Standard Time").name == "Asia/Riyadh"


def test_unknown_windows_zone_falls_back_to_the_system_zone(caplog):
    assert Z.resolve(None, "Not A Real Zone") == Z.ZoneChoice(None, "system")
    assert "Unknown Windows time zone" in caplog.text


def test_nothing_set_means_the_system_zone():
    assert Z.resolve(None, None) == Z.ZoneChoice(None, "system")


def test_system_choice_changes_nothing():
    assert Z.apply(Z.ZoneChoice(None, "system")) is False


@pytest.mark.skipif(hasattr(time, "tzset"), reason="Windows-only behaviour")
def test_native_windows_is_never_switched():
    """start.cmd must keep using Windows' own zone, whatever TZ says."""
    assert Z.apply(Z.ZoneChoice("Asia/Riyadh", "env")) is False


@pytest.mark.parametrize(
    "minutes,text", [(300, "UTC+5"), (180, "UTC+3"), (0, "UTC+0"), (330, "UTC+5:30"), (-240, "UTC-4")]
)
def test_offset_text(minutes, text):
    assert Z._fmt_offset(minutes) == text


def test_report_gives_the_page_what_it_compares():
    r = Z.report(Z.ZoneChoice("Asia/Karachi", "laptop"), datetime.now(dt_timezone.utc))
    assert r["name"] == "Asia/Karachi" and r["source"] == "laptop"
    assert isinstance(r["utc_offset_minutes"], int)
    assert r["utc_offset_text"].startswith("UTC")


@pytest.mark.parametrize("alias", ["Universal", "UCT", "Zulu", "Etc/UTC"])
def test_utc_is_called_utc(alias):
    """Seen in the real container: glibc named the default zone "Universal"."""
    r = Z.report(Z.ZoneChoice(alias, "env"), datetime.now(dt_timezone.utc))
    assert r["name"] == "UTC"
