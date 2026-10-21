"""Code-block and JSON boundary scanning helpers.

[INPUT]
- (none)

[OUTPUT]
- _is_inside_code_block(): Markdown code-block position check.
- _find_json_object_end(): balanced-brace JSON object end finder.

[POS]
Shared scanning primitives used by the XML/JSON format parsers.
"""

from __future__ import annotations


def _is_inside_code_block(content: str, position: int) -> bool:
    """Check if a given position is inside a Markdown code block"""
    before = content[:position]
    triple_backticks = before.count("```")
    return triple_backticks % 2 == 1


def _find_json_object_end(text: str) -> int:
    """Find the end position of a JSON object

    Args:
        text: Text starting with '{'

    Returns:
        JSON object end position (inclusive of '}'), or -1 if not found
    """
    if not text.startswith("{"):
        return -1

    depth = 0
    in_string = False
    escape_next = False

    for i, char in enumerate(text):
        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return i + 1

    return -1
