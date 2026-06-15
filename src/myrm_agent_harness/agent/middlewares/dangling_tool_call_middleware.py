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
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import BaseMessage, ToolMessage

logger = logging.getLogger(__name__)

_INTERRUPTED_CONTENT = "[Tool call was interrupted and did not return a result.]"
_INVALID_ARGS_CONTENT = "[Tool call could not be executed because its arguments were invalid.]"
_MAX_ERROR_DETAIL_LEN = 500


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
    existing_ids: set[str] = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            existing_ids.add(msg.tool_call_id)

    has_dangling = False
    for msg in messages:
        if getattr(msg, "type", None) != "ai":
            continue
        for tc_id, _, _ in _extract_tool_calls(msg):
            if tc_id not in existing_ids:
                has_dangling = True
                break
        if has_dangling:
            break

    if not has_dangling:
        return None

    patched: list[BaseMessage] = []
    patched_ids: set[str] = set()
    patched_names: list[str] = []

    for msg in messages:
        patched.append(msg)
        if getattr(msg, "type", None) != "ai":
            continue
        for tc_id, tool_name, is_invalid in _extract_tool_calls(msg):
            if tc_id in existing_ids or tc_id in patched_ids:
                continue
            error = None
            if is_invalid:
                for itc in getattr(msg, "invalid_tool_calls", None) or []:
                    if (itc.get("id") if isinstance(itc, dict) else getattr(itc, "id", None)) == tc_id:
                        error = itc.get("error") if isinstance(itc, dict) else getattr(itc, "error", None)
                        break
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

    logger.warning("Patched %d dangling tool call(s): %s", len(patched_names), ", ".join(patched_names))
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
