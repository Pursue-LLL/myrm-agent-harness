"""Text transforms for message content that is a string or a list of content blocks.

A message that carries an image next to its text (a chart from a tool, a screenshot from the user) has a block list
as its content. Security layers redact or rewrite its text and must leave everything else untouched.

[INPUT]
- none (pure functions)

[OUTPUT]
- MessageContent: the content type of a message (text, or text and image blocks)
- map_text_blocks: apply a text transform to a message content; of a block list only the text is transformed,
  image data and every other field pass through untouched

[POS]
Content-shape adapter between a message and the security layers that rewrite its text, so a layer treats a text
message and a text + image message alike.
"""

from __future__ import annotations

from collections.abc import Callable

MessageContent = str | list[str | dict[str, object]]


def map_text_blocks(content: MessageContent, transform: Callable[[str], str]) -> MessageContent:
    """Apply *transform* to the text of *content*: the string itself, or every block that carries text."""
    if isinstance(content, str):
        return transform(content)
    return [_map_block(block, transform) for block in content]


def _map_block(block: str | dict[str, object], transform: Callable[[str], str]) -> str | dict[str, object]:
    if isinstance(block, str):
        return transform(block)
    text = block.get("text")
    return {**block, "text": transform(text)} if isinstance(text, str) else block
