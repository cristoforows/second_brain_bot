from tags import extract_tags, count_tags, parse_blocks


def test_extract_tags_lowercased_distinct():
    assert extract_tags("ship #Work then more #work #todo") == {"work", "todo"}


def test_extract_tags_ignores_mid_word_hash_and_numbers_only():
    # '#' inside a word is not a tag; a numbers-only '#123' is not a tag.
    assert extract_tags("email a#b about issue #123") == set()
    assert extract_tags("plan #q3goals") == {"q3goals"}


def test_extract_tags_none():
    assert extract_tags("just a plain note") == set()


def test_count_tags_counts_notes_not_occurrences():
    notes = [
        "#work standup #work again",  # counts once for 'work'
        "#work review",
        "#todo buy milk",
    ]
    counts = count_tags(notes)
    assert counts["work"] == 2
    assert counts["todo"] == 1


def test_parse_blocks():
    content = (
        "# Telegram Messages\n\n"
        "<!-- msg_id: 1 -->\n#work thing\n"
        "<!-- msg_id: 2 -->\nplain\n"
    )
    assert parse_blocks(content) == ["#work thing", "plain"]
