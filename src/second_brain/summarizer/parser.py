from __future__ import annotations

import re

from second_brain.core.models import Message

_MSG_PATTERN = re.compile(
    r"<!--\s*msg_id:\s*(?P<id>[^\s]+)\s*-->\s*\n(?P<content>.*?)(?=<!--\s*msg_id:|\Z)",
    re.DOTALL,
)


def parse_dump(markdown: str) -> list[Message]:
    """Parse a markdown dump file into individual messages.

    Messages are delimited by ``<!-- msg_id: {id} -->`` HTML comments.
    Everything between one delimiter and the next (or end-of-file) is
    captured as the message content.

    Returns a list of :class:`Message` objects with leading/trailing
    whitespace stripped from each content block.
    """
    messages: list[Message] = []
    for match in _MSG_PATTERN.finditer(markdown):
        msg_id = match.group("id").strip()
        content = match.group("content").strip()
        if msg_id and content:
            messages.append(Message(id=msg_id, content=content))
    return messages
