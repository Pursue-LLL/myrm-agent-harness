"""Dangling tool call repair middleware.

When a user interrupts (/stop) or a request times out, the message history
may contain AIMessages with tool_calls that have no corresponding ToolMessages.
This violates the LLM API contract (OpenAI/Anthropic require every tool_call
to have a matching ToolMessage), causing all subsequent LLM calls to fail.

This middleware scans the message history before each LLM invocation and
inserts synthetic error ToolMessages for any dangling tool_calls, restoring
a well-formed conversation that the LLM can process.

Covers all three tool_call sources that langchain_openai serializes:
1. msg.tool_calls (standard parsed calls)
2. msg.invalid_tool_calls (malformed JSON args that LangChain failed to parse)
3. msg.additional_kwargs["tool_calls"] (raw provider-level payloads)

Uses wrap_model_call (not before_model) to insert patches at the correct
position — immediately after the dangling AIMessage — rather than appending
to the end via the add_messages reducer.

[INPUT]
- (none)

[OUTPUT]
- dangling_tool_call_middleware: Repair dangling tool_calls in message history before LLM ...

[POS]
Dangling tool call repair middleware.
"""

import logging
from copy import deepcopy
from json import JSONDecodeError, loads
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import BaseMessage, ToolMessage

logger = logging.getLogger(__name__)

_INTERRUPTED_CONTENT = "[Tool call was interrupted and did not return a result.]"
_INVALID_ARGS_CONTENT = "[Tool call could not be executed because its arguments were invalid.]"
_MAX_ERROR_DETAIL_LEN = 500


def _sanitize_tool_name(name: object) -> str:
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "unknown"


def _coerce_tool_args_object(args: object) -> dict[str, object]:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        stripped = args.strip()
        if len(stripped) >= 2 and stripped[0] in ("{", "["):
            try:
                parsed = loads(stripped)
                if isinstance(parsed, dict):
                    return {str(k): v for k, v in parsed.items()}
                if isinstance(parsed, list):
                    return {"items": parsed}
            except (ValueError, JSONDecodeError):
                return {}
    return {}


def _sanitize_tool_calls_list(raw_calls: object) -> tuple[list[dict[str, object]], bool]:
    if not isinstance(raw_calls, list):
        return [], bool(raw_calls)
    sanitized: list[dict[str, object]] = []
    changed = False
    for tc in raw_calls:
        if not isinstance(tc, dict):
            changed = True
            continue
        tc_id = tc.get("id")
        if not isinstance(tc_id, str) or not tc_id.strip():
            changed = True
            continue
        clean: dict[str, object] = dict(tc)
        clean["id"] = tc_id.strip()
        clean["name"] = _sanitize_tool_name(tc.get("name"))
        clean["args"] = _coerce_tool_args_object(tc.get("args"))
        if clean != tc:
            changed = True
        sanitized.append(clean)
    return sanitized, changed


def _sanitize_invalid_tool_calls_list(raw_calls: object) -> tuple[list[dict[str, object]], bool]:
    if not isinstance(raw_calls, list):
        return [], bool(raw_calls)
    sanitized: list[dict[str, object]] = []
    changed = False
    for tc in raw_calls:
        if not isinstance(tc, dict):
            changed = True
            continue
        tc_id = tc.get("id")
        if not isinstance(tc_id, str) or not tc_id.strip():
            changed = True
            continue
        clean: dict[str, object] = dict(tc)
        clean["id"] = tc_id.strip()
        clean["name"] = _sanitize_tool_name(tc.get("name"))
        error = tc.get("error")
        clean["error"] = error if isinstance(error, str) else None
        args = tc.get("args")
        clean["args"] = args if isinstance(args, str) else "{}"
        if clean != tc:
            changed = True
        sanitized.append(clean)
    return sanitized, changed


def _sanitize_raw_tool_calls_list(raw_calls: object) -> tuple[list[dict[str, object]], bool]:
    if not isinstance(raw_calls, list):
        return [], bool(raw_calls)
    sanitized: list[dict[str, object]] = []
    changed = False
    for tc in raw_calls:
        if not isinstance(tc, dict):
            changed = True
            continue
        tc_id = tc.get("id")
        if not isinstance(tc_id, str) or not tc_id.strip():
            changed = True
            continue

        function = tc.get("function")
        fn_dict = function if isinstance(function, dict) else {}
        fn_name = _sanitize_tool_name(tc.get("name") or fn_dict.get("name"))
        fn_arguments = fn_dict.get("arguments")
        if not isinstance(fn_arguments, str):
            fn_arguments = "{}"

        clean_function = dict(fn_dict)
        clean_function["name"] = fn_name
        clean_function["arguments"] = fn_arguments

        clean: dict[str, object] = dict(tc)
        clean["id"] = tc_id.strip()
        clean["type"] = clean.get("type") or "function"
        clean["function"] = clean_function
        if clean != tc:
            changed = True
        sanitized.append(clean)
    return sanitized, changed


def _sanitize_ai_message(msg: BaseMessage) -> bool:
    if getattr(msg, "type", None) != "ai":
        return False

    changed = False

    tool_calls, tc_changed = _sanitize_tool_calls_list(getattr(msg, "tool_calls", None))
    if tc_changed:
        changed = True
    if hasattr(msg, "tool_calls"):
        setattr(msg, "tool_calls", tool_calls)

    invalid_tool_calls, itc_changed = _sanitize_invalid_tool_calls_list(getattr(msg, "invalid_tool_calls", None))
    if itc_changed:
        changed = True
    if hasattr(msg, "invalid_tool_calls"):
        setattr(msg, "invalid_tool_calls", invalid_tool_calls)

    additional_kwargs = getattr(msg, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict) and "tool_calls" in additional_kwargs:
        raw_calls = additional_kwargs.get("tool_calls")
        sanitized_raw_calls, raw_changed = _sanitize_raw_tool_calls_list(raw_calls)
        if raw_changed:
            changed = True
            updated_kwargs = dict(additional_kwargs)
            updated_kwargs["tool_calls"] = sanitized_raw_calls
            setattr(msg, "additional_kwargs", updated_kwargs)

    return changed


def _extract_invalid_call_errors(msg: BaseMessage) -> dict[str, str]:
    errors: dict[str, str] = {}
    for itc in getattr(msg, "invalid_tool_calls", None) or []:
        if not isinstance(itc, dict):
            continue
        itc_id = itc.get("id")
        err = itc.get("error")
        if isinstance(itc_id, str) and itc_id and isinstance(err, str) and err:
            errors[itc_id] = err
    return errors


def _extract_tool_calls(msg: BaseMessage) -> list[tuple[str, str, bool]]:
    """Extract all tool call (id, name, is_invalid) tuples from an AIMessage.

    Covers the three sources that langchain_openai/_convert_message_to_dict
    serializes into the API request:
    1. msg.tool_calls — standard parsed calls
    2. msg.invalid_tool_calls — malformed calls (args failed JSON parsing)
    3. msg.additional_kwargs["tool_calls"] — raw provider payloads (fallback)
    """
    results: list[tuple[str, str, bool]] = []
    seen_ids: set[str] = set()

    for tc in getattr(msg, "tool_calls", None) or []:
        tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
        if tc_id and tc_id not in seen_ids:
            name = tc.get("name", "unknown") if isinstance(tc, dict) else getattr(tc, "name", "unknown")
            results.append((tc_id, name, False))
            seen_ids.add(tc_id)

    for itc in getattr(msg, "invalid_tool_calls", None) or []:
        itc_id = itc.get("id") if isinstance(itc, dict) else getattr(itc, "id", None)
        if itc_id and itc_id not in seen_ids:
            name = itc.get("name", "unknown") if isinstance(itc, dict) else getattr(itc, "name", "unknown")
            results.append((itc_id, name, True))
            seen_ids.add(itc_id)

    if not results:
        raw_tool_calls = (getattr(msg, "additional_kwargs", None) or {}).get("tool_calls") or []
        for raw_tc in raw_tool_calls:
            if not isinstance(raw_tc, dict):
                continue
            tc_id = raw_tc.get("id")
            if not tc_id or tc_id in seen_ids:
                continue
            function = raw_tc.get("function")
            name = raw_tc.get("name") or (function.get("name") if isinstance(function, dict) else None) or "unknown"
            results.append((tc_id, name, False))
            seen_ids.add(tc_id)

    return results


def _synthetic_content(is_invalid: bool, error: str | None = None) -> str:
    """Generate appropriate synthetic ToolMessage content."""
    if not is_invalid:
        return _INTERRUPTED_CONTENT
    if error:
        truncated = error[:_MAX_ERROR_DETAIL_LEN]
        return f"{_INVALID_ARGS_CONTENT[:-1]}: {truncated}]"
    return _INVALID_ARGS_CONTENT


def _build_patched_messages(messages: list[BaseMessage]) -> list[BaseMessage] | None:
    """Scan messages and insert synthetic ToolMessages for dangling tool_calls.

    For each AIMessage whose tool_calls (including invalid_tool_calls and
    additional_kwargs raw payloads) lack a corresponding ToolMessage, a
    synthetic error ToolMessage is inserted immediately after that AIMessage.

    Returns a new list with patches, or None if no patching is needed.
    """
    working = deepcopy(messages)
    changed = False
    ai_tool_calls_by_msg: dict[int, list[tuple[str, str, bool]]] = {}
    invalid_errors_by_msg: dict[int, dict[str, str]] = {}
    referenced_ids: set[str] = set()

    for msg in working:
        if _sanitize_ai_message(msg):
            changed = True
        if getattr(msg, "type", None) != "ai":
            continue
        tool_calls = _extract_tool_calls(msg)
        ai_tool_calls_by_msg[id(msg)] = tool_calls
        invalid_errors_by_msg[id(msg)] = _extract_invalid_call_errors(msg)
        for tc_id, _, _ in tool_calls:
            referenced_ids.add(tc_id)

    existing_ids: set[str] = set()
    for msg in working:
        if not isinstance(msg, ToolMessage):
            continue
        if msg.tool_call_id in referenced_ids:
            existing_ids.add(msg.tool_call_id)

    patched: list[BaseMessage] = []
    patched_ids: set[str] = set()
    patched_names: list[str] = []
    dropped_orphan_ids: list[str] = []

    for msg in working:
        if isinstance(msg, ToolMessage) and msg.tool_call_id not in referenced_ids:
            changed = True
            dropped_orphan_ids.append(msg.tool_call_id)
            continue

        patched.append(msg)
        if getattr(msg, "type", None) != "ai":
            continue
        tool_calls = ai_tool_calls_by_msg.get(id(msg), [])
        invalid_errors = invalid_errors_by_msg.get(id(msg), {})
        for tc_id, tool_name, is_invalid in tool_calls:
            if tc_id in existing_ids or tc_id in patched_ids:
                continue
            error = invalid_errors.get(tc_id) if is_invalid else None
            patched.append(
                ToolMessage(
                    content=_synthetic_content(is_invalid, error),
                    tool_call_id=tc_id,
                    name=tool_name,
                    status="error",
                )
            )
            patched_ids.add(tc_id)
            patched_names.append(tool_name)
            changed = True

    if not changed:
        return None

    if patched_names:
        logger.warning("Patched %d dangling tool call(s): %s", len(patched_names), ", ".join(patched_names))
    if dropped_orphan_ids:
        logger.warning(
            "Dropped %d orphan tool message(s): %s",
            len(dropped_orphan_ids),
            ", ".join(dropped_orphan_ids),
        )
    return patched


class DanglingToolCallMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Repair dangling tool_calls in message history before LLM invocation.

    Scans request.messages for AIMessages whose tool_calls have no matching
    ToolMessage, and inserts synthetic error responses at the correct position.
    """

    name = "dangling_tool_call_middleware"

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        patched = _build_patched_messages(list(request.messages))
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)


dangling_tool_call_middleware = DanglingToolCallMiddleware()
