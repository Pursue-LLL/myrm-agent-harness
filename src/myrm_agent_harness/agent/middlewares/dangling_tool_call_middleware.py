"""Dangling tool call repair middleware.

When a user interrupts (/stop) or a request times out, the message history
may contain AIMessages with tool_calls that have no corresponding ToolMessages.
This violates the LLM API contract (OpenAI/Anthropic require every tool_call
to have a matching ToolMessage), causing all subsequent LLM calls to fail.

This middleware scans the message history before each LLM invocation and
inserts synthetic error ToolMessages for any dangling tool_calls, restoring
a well-formed conversation that the LLM can process.

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


def _build_patched_messages(messages: list[BaseMessage]) -> list[BaseMessage] | None:
    """Scan messages and insert synthetic ToolMessages for dangling tool_calls.

    For each AIMessage whose tool_calls lack a corresponding ToolMessage,
    a synthetic error ToolMessage is inserted immediately after that AIMessage.

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
        for tc in getattr(msg, "tool_calls", None) or []:
            tc_id = tc.get("id")
            if tc_id and tc_id not in existing_ids:
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
        for tc in getattr(msg, "tool_calls", None) or []:
            tc_id = tc.get("id")
            if tc_id and tc_id not in existing_ids and tc_id not in patched_ids:
                tool_name = tc.get("name", "unknown")
                patched.append(
                    ToolMessage(content=_INTERRUPTED_CONTENT, tool_call_id=tc_id, name=tool_name, status="error")
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
        self,
        request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        patched = _build_patched_messages(list(request.messages))
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)

dangling_tool_call_middleware = DanglingToolCallMiddleware()
