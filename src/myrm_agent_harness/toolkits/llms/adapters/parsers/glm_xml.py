"""GLM XML tool call parsing (reasoning_content tool_call tags).

[INPUT]
- json::json (POS: Python JSON library)
- uuid::uuid4 (POS: UUID generator)
- logging (POS: Python logging)
- adapters.parsers.types (POS: tool-call type definitions)

[OUTPUT]
- _parse_glm_xml_format(): GLM XML tool call parsing.
- _scan_elements(): Linear-time ``<tag>payload</tag>`` extraction (no lazy-regex rescans on dangling openers).
- _normalize_arg_tags(): Repair a single missing <arg_value> open/close tag before pairing.
- _parse_arg_pairs(): Pair arg_key/arg_value tags in document order, reporting anomalies.

[POS]
GLM-family XML tool-call parser. Every scan over model output is linear in the block size:
a degenerate stream of dangling tags must not stall the event loop.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from myrm_agent_harness.toolkits.llms.adapters.parsers.types import ToolCallDict

logger = logging.getLogger(__name__)

_TOOL_CALL_OPEN = "<tool_call>"
_TOOL_CALL_CLOSE = "</tool_call>"
_ARG_KEY_OPEN = "<arg_key>"
_ARG_KEY_CLOSE = "</arg_key>"
_ARG_VALUE_OPEN = "<arg_value>"
_ARG_VALUE_CLOSE = "</arg_value>"

# (kind, opening tag, closing tag) of the elements ``_scan_elements`` extracts.
_TOOL_CALL_ELEMENT = (("tool_call", _TOOL_CALL_OPEN, _TOOL_CALL_CLOSE),)
_ARG_ELEMENTS = (("key", _ARG_KEY_OPEN, _ARG_KEY_CLOSE), ("value", _ARG_VALUE_OPEN, _ARG_VALUE_CLOSE))


def _splice(text: str, positions: list[int], insertion: str) -> str:
    """Insert ``insertion`` at every index in ``positions`` of ``text``."""
    if not positions:
        return text
    parts: list[str] = []
    prev = 0
    for pos in sorted(set(positions)):
        parts.append(text[prev:pos])
        parts.append(insertion)
        prev = pos
    parts.append(text[prev:])
    return "".join(parts)


class _ForwardFinder:
    """First occurrence of ``tag`` at or after a non-decreasing start index.

    A malformed stream can carry thousands of dangling tags; re-scanning from every
    start would make normalization quadratic. A remembered hit at or beyond ``start``
    is still the first one, and a miss stays a miss for any later start.
    """

    __slots__ = ("_hit", "_tag", "_text")

    def __init__(self, text: str, tag: str) -> None:
        self._text = text
        self._tag = tag
        self._hit = -2  # not searched yet

    def __call__(self, start: int) -> int:
        if self._hit != -1 and self._hit < start:
            self._hit = self._text.find(self._tag, start)
        return self._hit


def _scan_elements(text: str, kinds: tuple[tuple[str, str, str], ...]) -> list[tuple[str, str]]:
    """Return ``(kind, payload)`` for each ``<tag>payload</tag>`` element in document order.

    Linear-time equivalent of ``re.findall`` over the DOTALL alternation
    ``<kind>(.*?)</kind>``: a lazy regex rescans to the end of the text for every
    opener that never closes, which a degenerate stream of dangling openers turns
    into quadratic time. An opener without a closer is skipped (no later opener of
    that kind can be closed either); an element swallows any tags nested in its payload.
    """
    openers = [_ForwardFinder(text, open_tag) for _, open_tag, _ in kinds]
    closers = [_ForwardFinder(text, close_tag) for _, _, close_tag in kinds]
    elements: list[tuple[str, str]] = []
    pos = 0
    while True:
        hits = [(found, idx) for idx, find_open in enumerate(openers) if (found := find_open(pos)) != -1]
        if not hits:
            return elements
        open_at, idx = min(hits)
        kind, open_tag, close_tag = kinds[idx]
        start = open_at + len(open_tag)
        end = closers[idx](start)
        if end == -1:
            pos = start
            continue
        elements.append((kind, text[start:end]))
        pos = end + len(close_tag)


def _normalize_arg_tags(block: str) -> tuple[str, list[str]]:
    """Repair a missing ``<arg_value>`` open or close tag before pairing.

    GLM-family models sporadically drop exactly one of the two ``<arg_value>``
    tags while the value itself survives (vLLM #49248 for a dropped *opening*
    tag; Ollama #14656 for a dropped *closing* tag). Both stay recoverable as
    long as the value is bounded by the neighbouring key/tool tags:

    * a dropped opening tag is restored right after ``</arg_key>`` when the
      surviving text up to the next ``<arg_key>``/``</arg_value>`` is followed by
      a ``</arg_value>`` closer;
    * a dropped closing tag is restored immediately before the next
      ``<arg_key>`` (or the end of the block).

    ``</arg_value>`` remains the value delimiter, so well-formed blocks and the
    document-order pairing invariant are left byte-identical — only the two
    malformed shapes whose value otherwise would be discarded are rewritten.
    """

    anomalies: list[str] = []

    # Pass 1 — restore dropped opening tags. Every search is bounded to the window
    # between the previous closer and this one (the tags start with ``<`` only at
    # offset 0, so a match cannot straddle the bound), so the windows never overlap
    # and the pass stays linear.
    open_insertions: list[int] = []
    cursor = 0
    while True:
        window_start = cursor
        close_idx = block.find(_ARG_VALUE_CLOSE, window_start)
        if close_idx == -1:
            break
        cursor = close_idx + len(_ARG_VALUE_CLOSE)
        if block.find(_ARG_VALUE_OPEN, window_start, close_idx) != -1:
            # The closer already pairs with an opening tag in the same window.
            continue
        key_close_idx = block.rfind(_ARG_KEY_CLOSE, window_start, close_idx)
        if key_close_idx == -1:
            # No key owns this closer (an orphan value); leave it untouched.
            continue
        value_start = key_close_idx + len(_ARG_KEY_CLOSE)
        if block.find(_ARG_KEY_OPEN, value_start, close_idx) != -1:
            # The closer belongs to the key that follows this one; do not fold it in.
            continue
        open_insertions.append(value_start)

    if open_insertions:
        block = _splice(block, open_insertions, _ARG_VALUE_OPEN)
        anomalies.append("restored a missing <arg_value> opening tag")

    # Pass 2 — restore dropped closing tags (on the already-repaired text). Search
    # starts only move forward, so each finder scans the block once overall.
    close_insertions: list[int] = []
    find_value_close = _ForwardFinder(block, _ARG_VALUE_CLOSE)
    find_key_open = _ForwardFinder(block, _ARG_KEY_OPEN)
    find_key_close = _ForwardFinder(block, _ARG_KEY_CLOSE)
    cursor = 0
    while True:
        open_idx = block.find(_ARG_VALUE_OPEN, cursor)
        if open_idx == -1:
            break
        value_start = open_idx + len(_ARG_VALUE_OPEN)
        close_idx = find_value_close(value_start)
        next_key_idx = find_key_open(value_start)
        next_key_close_idx = find_key_close(next_key_idx) if next_key_idx != -1 else -1
        is_real_next_key = (
            next_key_idx != -1 and next_key_close_idx != -1 and (close_idx == -1 or next_key_close_idx < close_idx)
        )
        if is_real_next_key:
            # A genuine key starts before the value is closed: the closing tag was
            # dropped. (Requiring the key to be closed discriminates a real key
            # from a literal ``<arg_key>`` that merely appears inside the value.)
            close_insertions.append(next_key_idx)
            cursor = next_key_idx
        elif close_idx == -1:
            # The value runs to the end of a *matched* <tool_call> block. Because
            # the block's own ``</tool_call>`` arrived, this tool call is complete,
            # so the value it carries is complete too — close it.
            close_insertions.append(len(block))
            cursor = len(block)
        else:
            cursor = value_start

    if close_insertions:
        block = _splice(block, close_insertions, _ARG_VALUE_CLOSE)
        anomalies.append("restored a missing </arg_value> closing tag")

    return block, anomalies


def _parse_arg_pairs(xml: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Pair ``<arg_key>``/``<arg_value>`` tags strictly in document order.

    Input is expected to have passed ``_normalize_arg_tags``. Each value binds to
    the *immediately preceding* key, so pairing cannot shift a later value onto the
    wrong key. A key left without a value, or a value without a key, is reported as
    an anomaly (a truncated or malformed stream); the argument map is never collapsed
    silently.
    """
    pairs: list[tuple[str, str]] = []
    anomalies: list[str] = []
    pending_key: str | None = None

    for kind, payload in _scan_elements(xml, _ARG_ELEMENTS):
        text = payload.strip()
        if kind == "key":
            if pending_key is not None:
                anomalies.append(f"key '{pending_key}' has no value")
            pending_key = text
        elif pending_key is None:
            anomalies.append("value tag without a preceding key")
        else:
            pairs.append((pending_key, text))
            pending_key = None

    if pending_key is not None:
        anomalies.append(f"key '{pending_key}' has no value")

    return pairs, anomalies


def _parse_glm_xml_format(reasoning_content: str) -> list[ToolCallDict]:
    """Parse GLM XML format tool calls

    Format example:
    <tool_call>tool_name
    <arg_key>key1</arg_key>
    <arg_value>value1</arg_value>
    </tool_call>
    """
    if not reasoning_content or _TOOL_CALL_OPEN not in reasoning_content:
        return []

    tool_calls: list[ToolCallDict] = []

    matches = [payload for _, payload in _scan_elements(reasoning_content, _TOOL_CALL_ELEMENT)]

    for idx, match in enumerate(matches):
        try:
            # The function name may sit on its own line or be followed directly by
            # the first ``<arg_key>`` (GLM-4.7 emits the latter); take the text
            # before either delimiter so it never absorbs the argument stream.
            name_end = len(match)
            for delimiter in (_ARG_KEY_OPEN, _ARG_VALUE_OPEN):
                found = match.find(delimiter)
                if found != -1:
                    name_end = min(name_end, found)
            tool_name = match[:name_end].strip()

            if not tool_name:
                continue

            # Repair a single dropped ``<arg_value>`` open/close tag, then parse
            # parameters in document order so malformed tags are skipped rather
            # than positionally misaligned onto the wrong key.
            normalized, normalize_anomalies = _normalize_arg_tags(match)
            pairs, anomalies = _parse_arg_pairs(normalized)
            if normalize_anomalies or anomalies:
                logger.warning(
                    " GLM XML arg tags malformed for tool '%s': %s",
                    tool_name,
                    "; ".join(normalize_anomalies + anomalies),
                )

            args: dict[str, Any] = {}
            for key, value in pairs:
                # Try parsing JSON values (arrays, objects, etc.)
                try:
                    args[key] = json.loads(value)
                except json.JSONDecodeError:
                    args[key] = value

            # Build OpenAI-format tool_call
            tool_call: ToolCallDict = {
                "id": f"call_{uuid4().hex[:24]}",
                "index": idx,
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
                "type": "function",
            }
            tool_calls.append(tool_call)

            logger.debug(f" GLM XML parsed: {tool_name}, args={args}")

        except Exception as e:
            logger.warning(f" GLM XML Parsing failed: {e}")
            continue

    return tool_calls
