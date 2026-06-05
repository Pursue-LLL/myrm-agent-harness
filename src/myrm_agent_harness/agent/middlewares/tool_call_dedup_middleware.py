"""Tool call deduplication middleware.

Deduplicates ToolMessages with identical tool_call_ids before LLM invocation.
This addresses provider compatibility issues, notably Moonshot's ID reuse pattern
(e.g., "memory_store:0" used across multiple turns).

CRITICAL: Must run BEFORE dangling_tool_call_middleware to prevent synthetic
result insertion for duplicate IDs. Phase ordering:
- Phase 4 (THIS): Deduplication
- Phase 5 (AFTER): Synthetic missing results

[INPUT]
- ModelRequest with messages (POS: LangChain request type)

[OUTPUT]
- ModelRequest with deduplicated messages

[POS]
Tool call deduplication middleware. Ensures each tool_call_id appears at most
once in the ToolMessage list by keeping the last occurrence (most recent).
Prevents API failures when providers reuse IDs across turns.
"""

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import BaseMessage, ToolMessage

logger = logging.getLogger(__name__)


def _dedup_tool_messages(messages: list[BaseMessage]) -> list[BaseMessage] | None:
    """Deduplicate ToolMessages with identical tool_call_ids.

    Strategy: For each tool_call_id, keep only the LAST occurrence (most recent).
    This handles providers like Moonshot that reuse IDs across turns.

    Args:
        messages: Original message list

    Returns:
        Deduplicated list if duplicates found, None otherwise
    """
    seen_ids: dict[str, int] = {}
    tool_msg_indices: list[int] = []

    for i, msg in enumerate(messages):
        if isinstance(msg, ToolMessage) and msg.tool_call_id:
            tool_call_id = msg.tool_call_id
            if tool_call_id in seen_ids:
                old_idx = seen_ids[tool_call_id]
                logger.warning(
                    "Duplicate tool_call_id detected: %s (indices: %d, %d). Keeping last.", tool_call_id, old_idx, i
                )
                tool_msg_indices.append(old_idx)
            seen_ids[tool_call_id] = i

    if not tool_msg_indices:
        return None

    deduped = [msg for i, msg in enumerate(messages) if i not in tool_msg_indices]
    logger.warning(
        "Deduplicated %d tool message(s) with duplicate IDs: %s", len(tool_msg_indices), list(seen_ids.keys())
    )
    return deduped


class ToolCallDedupMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Deduplicate tool messages before LLM invocation.

    CRITICAL: Runs BEFORE dangling_tool_call_middleware to prevent synthetic
    insertion for duplicate IDs.
    """

    name = "tool_call_dedup_middleware"

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        deduped = _dedup_tool_messages(list(request.messages))
        if deduped is not None:
            request = request.override(messages=deduped)
        return await handler(request)


tool_call_dedup_middleware = ToolCallDedupMiddleware()
