"""Completion primitives for tool-argument JSON cut off mid-generation

[INPUT]
- re::re (POS: Python regex library)

[OUTPUT]
- close_truncated_json(): close the open string, dangling number/literal/key and containers of a cut-off JSON text
- ends_inside_string(): whether a JSON text stops inside an open string literal

[POS]
Pure text helpers with no trust policy: whether a completed value may be executed is
decided by the caller (``litellm_utils.parse_tool_call_arguments_with_recovery``).
"""

from __future__ import annotations

import re

_LITERAL_PREFIXES: dict[str, str] = {
    "t": "true",
    "tr": "true",
    "tru": "true",
    "f": "false",
    "fa": "false",
    "fal": "false",
    "fals": "false",
    "n": "null",
    "nu": "null",
    "nul": "null",
}
_LITERAL_TAIL_RE = re.compile(r"[{,:\[]\s*(t(?:r(?:u)?)?|f(?:a(?:l(?:s)?)?)?|n(?:u(?:l)?)?)\s*$")
_DANGLING_KEY_RE = re.compile(r'"\s*:\s*$')


def _scan(text: str) -> tuple[bool, list[str]]:
    """Return whether ``text`` ends inside a string literal and its still-open containers."""
    in_string = False
    escape_next = False
    # Stack tracks nesting order so closers are emitted in correct sequence
    stack: list[str] = []

    for char in text:
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in ("{", "["):
            stack.append(char)
        elif char in ("}", "]") and stack:
            stack.pop()

    return in_string, stack


def ends_inside_string(text: str) -> bool:
    """Whether the text stops inside an open string literal, i.e. a value was cut off mid-way."""
    return _scan(text)[0]


def close_truncated_json(text: str) -> str:
    """Close a JSON text that was cut off mid-generation so it can be parsed."""
    candidate = text.rstrip()
    if not candidate:
        return candidate

    in_string, stack = _scan(candidate)

    if in_string:
        # Odd trailing backslashes would escape the closing quote — strip the last one
        trailing = len(candidate) - len(candidate.rstrip("\\"))
        if trailing % 2 == 1:
            candidate = candidate[:-1]
        candidate += '"'

    candidate = re.sub(r",\s*$", "", candidate)
    # Fix truncated numeric fragments: sci-notation, trailing dot, bare minus
    candidate = re.sub(r"(\d[eE][+-]?)$", r"\g<1>0", candidate)
    candidate = re.sub(r"(\d)\.$", r"\g<1>.0", candidate)
    candidate = re.sub(r"([:,\[]\s*)-\s*$", r"\g<1>0", candidate)
    literal_match = _LITERAL_TAIL_RE.search(candidate)
    if literal_match:
        candidate = candidate[: literal_match.start(1)] + _LITERAL_PREFIXES[literal_match.group(1)]
    if _DANGLING_KEY_RE.search(candidate):
        candidate += " null"
    for opener in reversed(stack):
        candidate += "}" if opener == "{" else "]"
    return candidate
