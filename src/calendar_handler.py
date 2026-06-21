"""Google Calendar handler for publishing /timebox schedules.

Mirrors drive_handler: thin I/O over an authenticated Google API service built
from the user's stored credentials. All scheduling judgment lives in scheduler;
this module only turns a finished Schedule into calendar events.

Bot-created events are tagged so re-runs can clear-then-write idempotently
without touching the user's manual events (see docs/adr/0001).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from google_auth import get_google_service, TokenStorage

logger = logging.getLogger(__name__)

# Marker written to every bot event's private extended properties. The list/
# clear queries filter on it so only our events are ever removed.
SOURCE_KEY = "source"
SOURCE_VALUE = "timebox"


@dataclass
class WriteResult:
    """Outcome of writing one schedule item to the calendar."""

    task: str
    start: str
    end: str
    ok: bool


def get_calendar_service(user_id: int, token_storage: TokenStorage):
    """Get an authenticated Google Calendar API service for a user, or None."""
    return get_google_service(user_id, token_storage, "calendar", "v3")


def _slot_to_datetimes(target_date: date, start: str, end: str, tz: str) -> tuple[datetime, datetime]:
    """Combine the target date with HH:MM slot bounds into tz-aware datetimes.

    An end at or before the start is treated as crossing midnight into the next
    day (e.g. a 23:30-00:30 slot)."""
    zone = ZoneInfo(tz)
    sh, sm = (int(p) for p in start.split(":"))
    eh, em = (int(p) for p in end.split(":"))
    start_dt = datetime(target_date.year, target_date.month, target_date.day, sh, sm, tzinfo=zone)
    end_dt = datetime(target_date.year, target_date.month, target_date.day, eh, em, tzinfo=zone)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def _day_bounds(target_date: date, tz: str) -> tuple[str, str]:
    """RFC3339 [start, end) covering the whole target date in the given tz."""
    zone = ZoneInfo(tz)
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=zone)
    return day_start.isoformat(), (day_start + timedelta(days=1)).isoformat()


def list_timebox_events(service, calendar_id: str, target_date: date, tz: str) -> list[dict]:
    """Return the bot's own events on the target date (filtered by our tag)."""
    time_min, time_max = _day_bounds(target_date, tz)
    result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            privateExtendedProperty=f"{SOURCE_KEY}={SOURCE_VALUE}",
        )
        .execute()
    )
    return result.get("items", [])


def has_existing_schedule(service, calendar_id: str, target_date: date, tz: str) -> bool:
    """True if the bot has already written a schedule for the target date."""
    return len(list_timebox_events(service, calendar_id, target_date, tz)) > 0


def clear_timebox_events(service, calendar_id: str, target_date: date, tz: str) -> int:
    """Delete the bot's own events on the target date. Returns the count deleted."""
    events = list_timebox_events(service, calendar_id, target_date, tz)
    deleted = 0
    for event in events:
        try:
            service.events().delete(calendarId=calendar_id, eventId=event["id"]).execute()
            deleted += 1
        except Exception as e:
            logger.warning(f"Failed to delete timebox event {event.get('id')}: {e}")
    logger.info(f"Cleared {deleted}/{len(events)} timebox events for {target_date}")
    return deleted


def _event_body(item, target_date: date, tz: str) -> dict:
    start_dt, end_dt = _slot_to_datetimes(target_date, item.start, item.end, tz)
    body = {
        "summary": item.task,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": tz},
        "extendedProperties": {"private": {SOURCE_KEY: SOURCE_VALUE}},
    }
    if getattr(item, "note", None):
        body["description"] = item.note
    return body


def write_schedule(service, calendar_id: str, schedule, target_date: date, tz: str) -> list[WriteResult]:
    """Insert each schedule item as a tagged event; report per-item success.

    Never aborts on a single failure — every item is attempted so the caller can
    show the user exactly which slots made it onto the calendar."""
    results: list[WriteResult] = []
    for item in schedule:
        try:
            service.events().insert(calendarId=calendar_id, body=_event_body(item, target_date, tz)).execute()
            ok = True
        except Exception as e:
            logger.warning(f"Failed to write timebox event {item.task!r}: {e}")
            ok = False
        results.append(WriteResult(task=item.task, start=item.start, end=item.end, ok=ok))
    return results
