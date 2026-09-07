from __future__ import annotations

from datetime import timedelta

from second_brain.core.timeutil import today, yesterday


def test_yesterday_is_one_day_before_today() -> None:
    tz = "Asia/Singapore"
    assert today(tz) - yesterday(tz) == timedelta(days=1)


def test_today_respects_timezone_argument() -> None:
    # Different timezones can observe different calendar dates near midnight,
    # but both must be valid `date` objects derived from "now".
    utc_today = today("UTC")
    sgt_today = today("Asia/Singapore")
    assert abs((sgt_today - utc_today).days) <= 1
