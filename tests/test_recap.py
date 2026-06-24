from recap import parse_message_blocks


def test_parses_blocks_dropping_header():
    content = (
        "# Telegram Messages\n\n"
        "<!-- msg_id: 1 -->\nbuy milk\n"
        "<!-- msg_id: 2 -->\ncall the dentist\n"
    )
    assert parse_message_blocks(content) == ["buy milk", "call the dentist"]


def test_preserves_multiline_note():
    content = (
        "# Telegram Messages\n\n"
        "<!-- msg_id: 7 -->\nline one\nline two\n"
    )
    assert parse_message_blocks(content) == ["line one\nline two"]


def test_empty_or_header_only_returns_nothing():
    assert parse_message_blocks("") == []
    assert parse_message_blocks("# Telegram Messages\n\n") == []
