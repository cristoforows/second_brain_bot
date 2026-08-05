from weekly import parse_blocks, select_recent_daily, build_review_input


def test_select_recent_daily_filters_and_sorts():
    files = [
        {"id": "a", "name": "2026-06-20.md"},
        {"id": "b", "name": "2026-06-25.md"},
        {"id": "c", "name": "notes.md"},          # non-daily, ignored
        {"id": "d", "name": "2026-06-22.md"},
        {"id": "e", "name": "2026-06-26.md"},
    ]
    picked = select_recent_daily(files, days=3)
    assert [f["name"] for f in picked] == [
        "2026-06-26.md", "2026-06-25.md", "2026-06-22.md",
    ]


def test_select_recent_daily_empty():
    assert select_recent_daily([{"id": "x", "name": "readme.md"}]) == []


def test_parse_blocks():
    content = (
        "# Telegram Messages\n\n"
        "<!-- msg_id: 1 -->\nfirst\n"
        "<!-- msg_id: 2 -->\nsecond\n"
    )
    assert parse_blocks(content) == ["first", "second"]


def test_build_review_input_groups_by_day():
    out = build_review_input([
        ("2026-06-25", ["a", "b"]),
        ("2026-06-26", ["c"]),
    ])
    assert out == "## 2026-06-25\n- a\n- b\n\n## 2026-06-26\n- c"
