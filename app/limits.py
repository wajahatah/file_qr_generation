"""Time limits: turning "7 days" or a picked date into an instant, and back into words.

Pure functions, no I/O, so every edge case is unit-testable.

Semantics (spec section 4.1): a limit is a *calendar day*. "Until 5 October" means
all of 5 October in the laptop's local time. Internally that is stored as the instant
the limit runs out -- local midnight at the START of the following day -- in UTC. A
link is live while `now < expires_at`. Storing the next midnight rather than
23:59:59 means there is no one-second gap and no rounding to argue about.

Every function takes an optional `tz`. `None` means the operating system's local
zone, which is correct in the app because the app runs on the user's own laptop.
Tests pass an explicit zone so they do not depend on the machine running them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo

PRESET_DAYS: tuple[int, ...] = (1, 3, 7, 30)
EXTEND_DAYS: tuple[int, ...] = (7, 30)
DEFAULT_PRESET_DAYS = 7
MAX_DAYS_AHEAD = 365
# Google Drive empties its trash after 30 days; past that a file cannot be restored.
REACTIVATE_WINDOW_DAYS = 30


class LimitError(ValueError):
    """A limit the user asked for is not allowed. The message is shown to them."""


# ----------------------------------------------------------------- conversions


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def from_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _local(dt: datetime, tz: tzinfo | None) -> datetime:
    # astimezone() with no argument converts to the OS local zone.
    return dt.astimezone(tz) if tz is not None else dt.astimezone()


def local_today(now: datetime, tz: tzinfo | None = None) -> date:
    return _local(now, tz).date()


def expiry_instant(day: date, tz: tzinfo | None = None) -> datetime:
    """The UTC instant a limit of `day` runs out: local midnight starting day + 1."""
    nxt = day + timedelta(days=1)
    midnight = datetime(nxt.year, nxt.month, nxt.day)
    if tz is None:
        # A naive datetime's astimezone() applies the OS's rules *for that date*,
        # so a daylight-saving change between now and then is handled correctly.
        aware = midnight.astimezone()
    else:
        aware = midnight.replace(tzinfo=tz)
    return aware.astimezone(timezone.utc)


def last_day(expires_at: datetime, tz: tzinfo | None = None) -> date:
    """The calendar day shown to the user: the day before the expiry midnight."""
    return _local(expires_at - timedelta(seconds=1), tz).date()


# ---------------------------------------------------------------- choosing a day


def resolve_day(
    *,
    preset_days: int | None = None,
    until: date | None = None,
    now: datetime,
    tz: tzinfo | None = None,
) -> date:
    """Turn a preset or a picked date into the last day the QR works."""
    if (preset_days is None) == (until is None):
        raise LimitError("Choose either a preset or a date.")
    today = local_today(now, tz)
    if preset_days is not None:
        if preset_days not in PRESET_DAYS:
            raise LimitError(
                f"Choose one of {', '.join(str(d) for d in PRESET_DAYS)} days."
            )
        return today + timedelta(days=preset_days)
    return validate_day(until, now=now, tz=tz)  # type: ignore[arg-type]


def validate_day(day: date, *, now: datetime, tz: tzinfo | None = None) -> date:
    today = local_today(now, tz)
    if day < today:
        raise LimitError("That date has already passed.")
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        raise LimitError("A limit can be at most one year ahead.")
    return day


def extended_day(
    current_expires_at: datetime,
    extend_days: int,
    *,
    now: datetime,
    tz: tzinfo | None = None,
) -> date:
    """Add days to a limit, counting from its current last day or today if later.

    Counting from today when the link has already run out means "+7 days" on an
    expired link gives the customer a real seven days, not whatever is left of a
    window that closed last week.
    """
    if extend_days not in EXTEND_DAYS:
        raise LimitError(
            f"Extend by {' or '.join(str(d) for d in EXTEND_DAYS)} days."
        )
    base = max(last_day(current_expires_at, tz), local_today(now, tz))
    return validate_day(base + timedelta(days=extend_days), now=now, tz=tz)


# ------------------------------------------------------------------- the words


def fmt_day(day: date, *, with_year: bool = False) -> str:
    """'Sun 5 Oct', or 'Sun 5 Oct 2026'. No %-d: it is not portable to Windows."""
    s = f"{day:%a} {day.day} {day:%b}"
    return f"{s} {day.year}" if with_year else s


def _days_word(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


def limit_sentence(day: date, *, now: datetime, tz: tzinfo | None = None) -> str:
    """The sentence under the limit buttons (spec 4.1)."""
    n = (day - local_today(now, tz)).days
    span = "today only" if n == 0 else _days_word(n)
    return f"Customers can open this until {fmt_day(day, with_year=True)}, 11:59 PM ({span})"


@dataclass(frozen=True)
class Status:
    state: str  # active | expires_today | expiring | expired | ended
    text: str
    can_change: bool  # extend / shorten
    can_end: bool
    can_reactivate: bool


def describe(
    *,
    expires_at: datetime,
    revoked_at: datetime | None,
    removed_at: datetime | None,
    now: datetime,
    tz: tzinfo | None = None,
) -> Status:
    """Where a link stands, in plain words (spec 4.4)."""
    if revoked_at is not None:
        return Status(
            "ended", f"Ended · {fmt_day(_local(revoked_at, tz).date())}", False, False, False
        )

    end = last_day(expires_at, tz)

    if removed_at is not None:
        left = REACTIVATE_WINDOW_DAYS - (now - removed_at).days
        if left > 0:
            return Status(
                "expired",
                f"Expired · {fmt_day(end)} — can be reactivated for {_days_word(left)} more",
                False, False, True,
            )
        return Status("expired", f"Expired · {fmt_day(end)}", False, False, False)

    if now >= expires_at:
        # Past the limit but the app has not removed it from Drive yet -- the laptop
        # was off, or Drive was unreachable. The link still works until it is.
        return Status("expiring", "Expired — removing now", True, True, False)

    n = (end - local_today(now, tz)).days
    if n == 0:
        return Status("expires_today", "Expires today at 11:59 PM", True, True, False)
    return Status(
        "active", f"Active · until {fmt_day(end)} ({_days_word(n)} left)", True, True, False
    )


def can_reactivate(removed_at: datetime | None, revoked_at: datetime | None, now: datetime) -> bool:
    if removed_at is None or revoked_at is not None:
        return False
    return (now - removed_at).days < REACTIVATE_WINDOW_DAYS
