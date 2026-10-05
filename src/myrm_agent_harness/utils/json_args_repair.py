"""JSON args repair and outbound invalid-call quarantine (replay-poisoning defense).

Some providers emit malformed tool_call arguments — raw control characters,
invalid escapes, truncated JSON — and langchain_openai serializes
``AIMessage.invalid_tool_calls`` verbatim back into the API request
(``_convert_message_to_dict`` merges them into the outbound ``tool_calls``).
Replaying the malformed text teaches the model to imitate its own broken
format, degrading the whole session (history poisoning). This module keeps
such records from ever reaching the provider in raw form.

[INPUT]
- json_parsing (harness): low-level JSON text repair primitives
  (control-char escaping, trailing-comma stripping)

[OUTPUT]
- ArgsRepairResult: frozen outcome of one repair attempt
- repair_json_args(): deterministic escape-level repair for one tool_call
  args string. Only syntax-safe transforms (escaping, comma removal,
  truncation closure); no content guessing. Succeeds only when the result
  parses as a JSON object.
- quarantine_invalid_tool_calls(): outbound poison isolation — upgrade each
  AIMessage.invalid_tool_call into a well-formed tool_call declaration
  (repaired args, or empty args + structured diagnosis when unrepairable).
  Deterministic and idempotent, so repeated runs produce identical output
  (prompt-cache friendly).

[POS]
Pure repair + langchain-message quarantine shared by the dangling repair
pipeline (outbound) and the ToolNode args guard (inbound coercion).
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from langchain_core.messages import BaseMessage

from myrm_agent_harness.utils.json_parsing import (
    _escape_control_chars_in_strings,
    _strip_trailing_commas,
)


@dataclass(frozen=True)
class ArgsRepairResult:
    """Outcome of one ``repair_json_args`` attempt.

    ``repaired``/``args`` are set together on success (args is the parsed
    object form); ``diagnosis`` is a key-path error summary on failure.
    """

    repaired: str | None
    args: dict[str, object] | None
    diagnosis: str | None


def _close_truncation(text: str) -> str:
    """Close string literals and containers truncated mid-stream.

    Stream truncation leaves args like ``{"path": "repor`` or ``{"a": {"b": 1``.
    A single state-machine pass tracks open strings and the container stack;
    the missing closers are appended in order. A dangling escape at the cut
    point is dropped first (escaping the closing quote would be an invalid
    JSON escape). Content is never fabricated — only syntax closed.
    """
    stack: list[str] = []
    in_string = False
    escape_next = False
    for ch in text:
        if in_string:
            if escape_next:
                escape_next = False
            elif ch == "\\":
                escape_next = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif (ch == "}" and stack and stack[-1] == "{") or (ch == "]" and stack and stack[-1] == "["):
            stack.pop()
    if in_string:
        # A dangling backslash must be dropped before appending the closing
        # quote: escaping it ('\ ') would produce an invalid JSON escape.
        if escape_next:
            text = text[:-1]
        return text + '"' + "".join("}" if c == "{" else "]" for c in reversed(stack))
    return text + "".join("}" if c == "{" else "]" for c in reversed(stack))


def _key_path_at(text: str, pos: int) -> str:
    """Return the dotted key path enclosing ``pos`` for diagnostics.

    Tracks the last completed key literal per open object so failures can be
    reported as ``a.b.c`` instead of a bare character offset. Array levels are
    skipped (no key) and closed containers are popped, keeping the path
    anchored to the failure point.
    """
    stack: list[tuple[str, str | None]] = []  # (container_type, last_key)
    expect_key = False
    in_string = False
    escape_next = False
    chars: list[str] = []
    for idx, ch in enumerate(text):
        if idx >= pos:
            break
        if in_string:
            if escape_next:
                escape_next = False
            elif ch == "\\":
                escape_next = True
            elif ch == '"':
                in_string = False
                if expect_key and stack:
                    stack[-1] = ("obj", "".join(chars))
                    expect_key = False
            else:
                chars.append(ch)
            continue
        if ch == '"':
            in_string = True
            chars = []
        elif ch == "{":
            stack.append(("obj", None))
            expect_key = True
        elif ch == "[":
            stack.append(("arr", None))
            expect_key = False
        elif ch in "}]":
            if stack:
                stack.pop()
        elif ch == "," and stack and stack[-1][0] == "obj":
            expect_key = True
    return ".".join(key for _, key in stack if key)


def _diagnose(text: str) -> str:
    """Produce a key-path style parse diagnosis for an unrepairable args string."""
    try:
        json.loads(text)  # always malformed at this call site
    except json.JSONDecodeError as err:
        path = _key_path_at(text, err.pos)
        where = f' at key "{path}"' if path else ""
        return f"args{where} failed to parse (char {err.pos}): {err.msg}"
    return "args failed to parse"  # pragma: no cover - unreachable when malformed


def _try_load_dict(text: str) -> dict[str, object] | None:
    """Parse ``text`` as a JSON object, returning ``None`` on any failure."""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, RecursionError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def repair_json_args(text: str) -> ArgsRepairResult:
    """Deterministically repair one malformed tool_call args string.

    Pipeline (each tier only ever makes syntax-safe changes, verified by
    a strict parse — no content is guessed, inserted, or dropped):
    1. strict parse (fast path for well-formed args)
    2. escape raw control characters inside string literals
    3. strip trailing commas
    4. close truncation (open strings / containers), then re-strip commas

    Succeeds only when the result parses as a JSON *object* (function
    arguments must be an object); anything else returns a structured
    diagnosis for the caller's invalid-args path.
    """
    stripped = text.strip()
    if not stripped:
        return ArgsRepairResult(None, None, "args failed to parse: empty arguments")

    args = _try_load_dict(stripped)
    if args is not None:
        return ArgsRepairResult(stripped, args, None)

    escaped = _escape_control_chars_in_strings(stripped)
    for candidate in (escaped, _strip_trailing_commas(escaped)):
        args = _try_load_dict(candidate)
        if args is not None:
            return ArgsRepairResult(candidate, args, None)

    closed = _close_truncation(_strip_trailing_commas(escaped))
    closed = _strip_trailing_commas(closed)
    args = _try_load_dict(closed)
    if args is not None:
        return ArgsRepairResult(closed, args, None)
    return ArgsRepairResult(None, None, _diagnose(closed))


def _raw_tool_call_arguments_by_id(msg: BaseMessage) -> dict[str, dict[str, object]]:
    """Index ``additional_kwargs["tool_calls"]`` function dicts by call id.

    Returns the *live* function dicts so callers can update
    ``function["arguments"]`` in place, keeping the raw provider payload
    consistent with the sanitized declaration (``_convert_message_to_dict``
    may read either source depending on langchain version).
    """
    kwargs = getattr(msg, "additional_kwargs", None)
    raw_calls = kwargs.get("tool_calls") if isinstance(kwargs, dict) else None
    if not isinstance(raw_calls, list):
        return {}
    indexed: dict[str, dict[str, object]] = {}
    for raw in cast(Iterable[object], raw_calls):
        if not isinstance(raw, dict):
            continue
        tc_id = raw.get("id")
        function = raw.get("function")
        if isinstance(tc_id, str) and isinstance(function, dict):
            indexed[tc_id] = function
    return indexed


def quarantine_invalid_tool_calls(msg: BaseMessage) -> dict[str, str]:
    """Outbound poison isolation: neutralize ``msg.invalid_tool_calls`` in place.

    Each invalid call is upgraded into a well-formed ``tool_calls`` entry on
    the same message, keeping its id and name:
    - repairable args → parsed repaired args (the model sees the call it
      *meant* to make; the dangling pipeline then pairs it with a synthetic
      interrupted ToolMessage per replay safety)
    - unrepairable args → empty args and a structured key-path diagnosis,
      returned as ``{tool_call_id: diagnosis}`` so the dangling pipeline can
      pair it with an informative invalid-args ToolMessage

    Malformed raw text never leaves the process afterwards: the matching
    ``additional_kwargs`` raw payloads are synced to the same sanitized
    arguments. Idempotent — on the second pass ``invalid_tool_calls`` is
    empty and nothing changes.
    """
    invalid_calls = getattr(msg, "invalid_tool_calls", None)
    if not isinstance(invalid_calls, list) or not invalid_calls:
        return {}
    if getattr(msg, "type", None) != "ai":
        return {}

    valid_calls = list(getattr(msg, "tool_calls", None) or [])
    known_ids = {
        tc.get("id") for tc in cast(Iterable[dict[str, object]], valid_calls) if isinstance(tc, dict)
    }
    upgraded: list[dict[str, object]] = []
    errors: dict[str, str] = {}
    arguments_by_id: dict[str, str] = {}
    raw_functions = _raw_tool_call_arguments_by_id(msg)

    for itc in cast(Iterable[object], invalid_calls):
        if not isinstance(itc, dict):
            continue
        raw_id = itc.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip() or raw_id in known_ids:
            continue
        tc_id = raw_id.strip()
        raw_name = itc.get("name")
        tool_name = raw_name if isinstance(raw_name, str) and raw_name.strip() else "unknown"
        raw_args = itc.get("args")
        result = (
            repair_json_args(raw_args)
            if isinstance(raw_args, str)
            else ArgsRepairResult(None, None, "args failed to parse: non-string arguments")
        )
        if result.args is not None:
            upgraded.append({"name": tool_name, "args": result.args, "id": tc_id, "type": "tool_call"})
            arguments_by_id[tc_id] = result.repaired or json.dumps(result.args)
            continue
        errors[tc_id] = result.diagnosis or "args failed to parse"
        upgraded.append({"name": tool_name, "args": {}, "id": tc_id, "type": "tool_call"})
        arguments_by_id[tc_id] = "{}"

    if not upgraded:
        return {}

    msg.tool_calls = [*valid_calls, *upgraded]  # type: ignore[attr-defined]
    msg.invalid_tool_calls = []  # type: ignore[attr-defined]
    for tc_id, arguments in arguments_by_id.items():
        raw_function = raw_functions.get(tc_id)
        if raw_function is not None:
            raw_function["arguments"] = arguments
    return errors
