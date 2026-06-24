from search import parse_blocks, find_matches, _snippet, _date_of

CONTENT = (
    "# Telegram Messages\n\n"
    "<!-- msg_id: 1 -->\nBook dentist appointment\n"
    "<!-- msg_id: 2 -->\nGroceries: milk, eggs\n"
    "<!-- msg_id: 3 -->\nDENTIST follow-up next month\n"
)


def test_parse_blocks():
    assert parse_blocks(CONTENT) == [
        "Book dentist appointment",
        "Groceries: milk, eggs",
        "DENTIST follow-up next month",
    ]


def test_find_matches_is_case_insensitive():
    hits = find_matches(CONTENT, "dentist")
    assert hits == ["Book dentist appointment", "DENTIST follow-up next month"]


def test_find_matches_none():
    assert find_matches(CONTENT, "passport") == []


def test_snippet_collapses_and_truncates():
    assert _snippet("line one\n  line  two") == "line one line two"
    long = "x" * 300
    out = _snippet(long)
    assert out.endswith("…") and len(out) <= 161


def test_date_of():
    assert _date_of("2026-06-25.md") == "2026-06-25"
    assert _date_of("weird.md") == "weird.md"
