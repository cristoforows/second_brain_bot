from datetime import date

from second_brain.bot import calendar_handler
from second_brain.bot.calendar_handler import (
    SOURCE_KEY,
    SOURCE_VALUE,
    clear_timebox_events,
    has_existing_schedule,
    list_timebox_events,
    write_schedule,
)
from second_brain.bot.timebox_planner import ScheduleItem

SG = "Asia/Singapore"  # UTC+8, no DST
CAL = "abc@group.calendar.google.com"
DAY = date(2026, 6, 12)


class FakeRequest:
    def __init__(self, store, op, payload):
        self.store, self.op, self.payload = store, op, payload

    def execute(self):
        return self.store._apply(self.op, self.payload)


class FakeEvents:
    """Minimal stand-in for service.events() with an in-memory store."""

    def __init__(self, store):
        self.store = store

    def list(self, **kwargs):
        return FakeRequest(self.store, "list", kwargs)

    def insert(self, **kwargs):
        return FakeRequest(self.store, "insert", kwargs)

    def delete(self, **kwargs):
        return FakeRequest(self.store, "delete", kwargs)


class FakeCalendarService:
    def __init__(self, items=None, fail_inserts_for=()):
        self.items = list(items or [])
        self.fail_inserts_for = set(fail_inserts_for)
        self.inserted = []
        self.deleted = []
        self.list_calls = []

    def events(self):
        return FakeEvents(self)

    def _apply(self, op, payload):
        if op == "list":
            self.list_calls.append(payload)
            prop = payload.get("privateExtendedProperty")
            items = self.items
            if prop:
                key, value = prop.split("=")
                items = [
                    e
                    for e in items
                    if e.get("extendedProperties", {}).get("private", {}).get(key) == value
                ]
            return {"items": items}
        if op == "insert":
            body = payload["body"]
            if body["summary"] in self.fail_inserts_for:
                raise RuntimeError("insert failed")
            self.inserted.append(body)
            return {"id": f"id-{len(self.inserted)}", **body}
        if op == "delete":
            self.deleted.append(payload["eventId"])
            self.items = [e for e in self.items if e["id"] != payload["eventId"]]
            return {}
        raise AssertionError(op)


def _tagged(event_id, summary="Lunch"):
    return {
        "id": event_id,
        "summary": summary,
        "extendedProperties": {"private": {SOURCE_KEY: SOURCE_VALUE}},
    }


def _manual(event_id, summary="Dentist"):
    return {"id": event_id, "summary": summary}


# --- list / existence ---


def test_list_returns_only_tagged_events():
    svc = FakeCalendarService(items=[_tagged("a"), _manual("b")])
    out = list_timebox_events(svc, CAL, DAY, SG)
    assert [e["id"] for e in out] == ["a"]


def test_has_existing_true_only_when_tagged_event_present():
    assert has_existing_schedule(FakeCalendarService(items=[_tagged("a")]), CAL, DAY, SG)
    assert not has_existing_schedule(FakeCalendarService(items=[_manual("b")]), CAL, DAY, SG)
    assert not has_existing_schedule(FakeCalendarService(items=[]), CAL, DAY, SG)


def test_list_scopes_query_to_the_target_day():
    svc = FakeCalendarService(items=[_tagged("a")])
    list_timebox_events(svc, CAL, DAY, SG)
    call = svc.list_calls[0]
    assert call["timeMin"].startswith("2026-06-12T00:00:00")
    assert call["timeMax"].startswith("2026-06-13T00:00:00")


# --- clear ---


def test_clear_deletes_only_tagged_events():
    svc = FakeCalendarService(items=[_tagged("a"), _manual("b"), _tagged("c")])
    deleted = clear_timebox_events(svc, CAL, DAY, SG)
    assert deleted == 2
    assert set(svc.deleted) == {"a", "c"}


# --- write ---


def test_write_inserts_tagged_timed_events_with_local_tz():
    svc = FakeCalendarService()
    items = [ScheduleItem(start="09:00", end="10:30", task="deep work", note="focus")]
    results = write_schedule(svc, CAL, items, DAY, SG)

    assert len(svc.inserted) == 1
    body = svc.inserted[0]
    assert body["summary"] == "deep work"
    assert body["description"] == "focus"
    assert body["start"]["dateTime"] == "2026-06-12T09:00:00+08:00"
    assert body["end"]["dateTime"] == "2026-06-12T10:30:00+08:00"
    assert body["extendedProperties"]["private"][SOURCE_KEY] == SOURCE_VALUE
    assert results[0].ok is True


def test_write_reports_per_item_success_and_failure():
    svc = FakeCalendarService(fail_inserts_for={"Dinner"})
    items = [
        ScheduleItem(start="09:00", end="10:00", task="gym"),
        ScheduleItem(start="19:00", end="20:00", task="Dinner"),
        ScheduleItem(start="20:30", end="21:00", task="read"),
    ]
    results = write_schedule(svc, CAL, items, DAY, SG)

    by_task = {r.task: r.ok for r in results}
    assert by_task == {"gym": True, "Dinner": False, "read": True}
    # the failure does not stop later inserts
    assert {b["summary"] for b in svc.inserted} == {"gym", "read"}


def test_write_handles_slot_crossing_midnight():
    svc = FakeCalendarService()
    items = [ScheduleItem(start="23:30", end="00:30", task="wind down")]
    write_schedule(svc, CAL, items, DAY, SG)
    body = svc.inserted[0]
    assert body["start"]["dateTime"] == "2026-06-12T23:30:00+08:00"
    assert body["end"]["dateTime"] == "2026-06-13T00:30:00+08:00"
