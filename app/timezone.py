"""Which time zone the app counts time limits in.

A limit is a calendar day in local time (limits.py), so the zone decides when "until
5 October" really ends. Natively the app simply uses Windows' zone. In Docker the
container's clock is UTC unless told otherwise, so the zone is resolved here
(spec-docker 3.3, revised):

  1. TZ, if set                      -- explicit override from .env
  2. HOST_WINDOWS_TZ, if set         -- the laptop's Windows zone, passed in by
                                        docker-start.cmd, translated to its IANA name
  3. otherwise the system default    -- UTC in a container

Only applied where the C library can switch zones at runtime (time.tzset exists, i.e.
Linux). On Windows the process already runs in Windows' zone and nothing is changed.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ZoneChoice:
    name: str | None  # IANA name, or None for "whatever the system uses"
    source: str  # "env" | "laptop" | "system"


def windows_to_iana(windows_name: str) -> str | None:
    """'Pakistan Standard Time' -> 'Asia/Karachi', using the CLDR table in tzlocal."""
    from tzlocal.windows_tz import win_tz  # noqa: PLC0415

    return win_tz.get(windows_name.strip())


def resolve(tz_env: str | None, host_windows_tz: str | None) -> ZoneChoice:
    if tz_env and tz_env.strip():
        return ZoneChoice(tz_env.strip(), "env")
    if host_windows_tz and host_windows_tz.strip():
        iana = windows_to_iana(host_windows_tz)
        if iana:
            return ZoneChoice(iana, "laptop")
        log.warning("Unknown Windows time zone %r; falling back to the system zone", host_windows_tz)
    return ZoneChoice(None, "system")


def apply(choice: ZoneChoice) -> bool:
    """Switch this process to `choice`. Returns True if the zone was changed."""
    if choice.name is None or not hasattr(time, "tzset"):
        return False
    os.environ["TZ"] = choice.name
    time.tzset()
    log.info("Time limits use time zone %s (from %s)", choice.name, choice.source)
    return True


def report(choice: ZoneChoice, now_utc: datetime) -> dict:
    """What the page shows, and the offset it compares with the browser's own."""
    local = now_utc.astimezone()
    offset = local.utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset is not None else 0
    name = choice.name or local.tzname() or "UTC"
    # glibc calls an unset/empty zone "Universal"; say what a person expects.
    if name in _UTC_ALIASES:
        name = "UTC"
    return {
        "name": name,
        "source": choice.source,
        "utc_offset_minutes": minutes,
        "utc_offset_text": _fmt_offset(minutes),
    }


_UTC_ALIASES = {"Universal", "UCT", "Zulu", "Etc/UTC", "Etc/Universal", "GMT", "UTC"}


def _fmt_offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    h, m = divmod(abs(minutes), 60)
    return f"UTC{sign}{h}" if m == 0 else f"UTC{sign}{h}:{m:02d}"
