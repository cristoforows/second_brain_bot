from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def today(tz: str) -> date:
    """Return the current date in the given IANA timezone."""
    return datetime.now(ZoneInfo(tz)).date()


def yesterday(tz: str) -> date:
    """Return the date before today in the given IANA timezone."""
    return today(tz) - timedelta(days=1)
