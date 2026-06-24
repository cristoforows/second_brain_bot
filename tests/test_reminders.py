import pytest

from reminders import parse_reminder, humanize


@pytest.mark.parametrize("arg,expected", [
    ("30m drink water", (1800, "drink water")),
    ("2h call the dentist", (7200, "call the dentist")),
    ("1d renew passport", (86400, "renew passport")),
    ("90 standup", (5400, "standup")),            # bare number = minutes
    ("45s ping", (45, "ping")),
    ("1h  spaced  out ", (3600, "spaced  out")),
])
def test_parse_valid(arg, expected):
    assert parse_reminder(arg) == expected


@pytest.mark.parametrize("arg", [
    "",                # empty
    "drink water",     # no duration
    "30m",             # no text
    "0m nothing",      # zero
    "31d too far",     # over the 30-day cap
    "abc do thing",    # unparseable duration
])
def test_parse_invalid(arg):
    assert parse_reminder(arg) is None


def test_humanize():
    assert humanize(45) == "45s"
    assert humanize(1800) == "30m"
    assert humanize(9000) == "2h 30m"
    assert humanize(90000) == "1d 1h"
