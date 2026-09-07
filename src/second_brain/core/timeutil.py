from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def today(tz: str) -> date:
    """Return the current date in the given IANA timezone."""
    return datetime.now(ZoneInfo(tz)).date()


def yesterday(tz: str) -> date:
    """Return the date before today in the given IANA timezone."""
    return today(tz) - timedelta(days=1)


def capture_date(now: datetime, tz: str, day_cutoff_hour: int) -> date:
    """Return the calendar date a captured message belongs to.

    Applies `day_cutoff_hour` in `tz` (an IANA timezone name), not the
    container's local clock. For example, with day_cutoff_hour=4 a message
    captured at 02:30 local time belongs to the *previous* day's file.
    `now` may be naive (assumed to already be in `tz`) or tz-aware (converted
    to `tz` first).
    """
    zone = ZoneInfo(tz)
    local = now.astimezone(zone) if now.tzinfo is not None else now.replace(tzinfo=zone)
    if day_cutoff_hour > 0 and local.hour < day_cutoff_hour:
        return (local - timedelta(days=1)).date()
    return local.date()
