from second_brain.core.models import Message
from second_brain.utils.parser import parse_dump


def test_parse_sample_dump(sample_dump_text: str) -> None:
    messages = parse_dump(sample_dump_text)
    assert len(messages) == 5
    assert all(isinstance(m, Message) for m in messages)


def test_message_ids_are_correct(sample_dump_text: str) -> None:
    messages = parse_dump(sample_dump_text)
    expected_ids = ["msg-001", "msg-002", "msg-003", "msg-004", "msg-005"]
    assert [m.id for m in messages] == expected_ids


def test_message_content_is_stripped(sample_dump_text: str) -> None:
    messages = parse_dump(sample_dump_text)
    for msg in messages:
        assert msg.content == msg.content.strip()
        assert len(msg.content) > 0


def test_first_message_content(sample_dump_text: str) -> None:
    messages = parse_dump(sample_dump_text)
    assert "productive meeting with the design team" in messages[0].content


def test_last_message_content(sample_dump_text: str) -> None:
    messages = parse_dump(sample_dump_text)
    assert "Project alpha deadline" in messages[4].content


def test_empty_input() -> None:
    assert parse_dump("") == []


def test_no_delimiters() -> None:
    assert parse_dump("Just some plain text without any markers.") == []


def test_single_message() -> None:
    md = "<!-- msg_id: only-one -->\nHello world."
    messages = parse_dump(md)
    assert len(messages) == 1
    assert messages[0].id == "only-one"
    assert messages[0].content == "Hello world."


def test_multiline_content() -> None:
    md = (
        "<!-- msg_id: multi -->\n"
        "Line one.\n"
        "\n"
        "Line two with a gap.\n"
    )
    messages = parse_dump(md)
    assert len(messages) == 1
    assert "Line one." in messages[0].content
    assert "Line two with a gap." in messages[0].content


def test_whitespace_in_delimiter() -> None:
    md = "<!--   msg_id:   spaced-id   -->\nContent here."
    messages = parse_dump(md)
    assert len(messages) == 1
    assert messages[0].id == "spaced-id"
