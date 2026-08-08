"""Provider Safety — normalize messages before LLM calls.

Inspired by lime's provider_safety.rs, adapted for LangChain architecture.

[INPUT]
- langchain_core.messages::BaseMessage (POS: Core message type definitions. All cross-channel communication data structures are defined here; zero I/O, pure data.)
- agent.middlewares.tool_history_hygiene::sanitize_tool_history (POS: Tool history hygiene middleware. Runs BEFORE dangling_tool_call_middleware.)

[OUTPUT]
- normalize_messages(): Clean invalid tool calls, orphan responses, and duplicate tool_call_ids

[POS]
Provider safety normalization. Pure function for direct LLM paths; agent middleware covers the primary runtime.
"""

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


def normalize_messages(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Normalize message chain before sending to LLM provider.

    Removes:
    1. Invalid tool requests (wrong role or failed parsing)
    2. Orphan tool responses (no matching request)
    3. Duplicate tool responses (multiple responses for same request)

    Ensures strict tool request-response pairing and global tool_call_id uniqueness.

    Args:
        messages: Original message sequence

    Returns:
        Cleaned message list (may be shorter)

    Example:
        >>> messages = [
        ...     HumanMessage(content="run ls"),
        ...     AIMessage(content="", tool_calls=[{"id": "1", "name": "bash", "args": {...}}]),
        ...     ToolMessage(content="file.txt", tool_call_id="1"),
        ... ]
        >>> normalized = normalize_messages(messages)
        >>> len(normalized) == 3  # All valid
    """
    if not messages:
        return []

    from myrm_agent_harness.agent.middlewares.tool_history_hygiene import (
        sanitize_tool_history,
    )

    working = sanitize_tool_history(list(messages))

    # Collect valid tool request IDs
    valid_request_ids: set[str] = set()
    matched_request_ids: set[str] = set()
    removed_invalid_requests = 0
    removed_invalid_responses = 0

    normalized: list[BaseMessage] = []

    # First pass: collect valid requests and filter messages
    for msg in working:
        if isinstance(msg, AIMessage):
            # Check tool_calls validity
            if msg.tool_calls:
                valid_calls = []
                for tc in msg.tool_calls:
                    # Tool call must have id and valid structure
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tc_id and isinstance(tc_id, str):
                        valid_request_ids.add(tc_id)
                        valid_calls.append(tc)
                    else:
                        removed_invalid_requests += 1

                # Keep message only if it has valid content or valid tool calls
                if valid_calls or msg.content:
                    cloned = msg.model_copy(deep=True)
                    cloned.tool_calls = valid_calls
                    normalized.append(cloned)
                # else: drop message entirely (no content, no valid tools)
            else:
                # No tool calls, keep as-is
                normalized.append(msg)

        elif isinstance(msg, ToolMessage):
            # Tool response must have matching request
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id and tc_id in valid_request_ids and tc_id not in matched_request_ids:
                matched_request_ids.add(tc_id)
                normalized.append(msg)
            else:
                removed_invalid_responses += 1

        else:
            # HumanMessage, SystemMessage, etc. — keep as-is
            normalized.append(msg)

    # Second pass: filter to keep only matched tool pairs
    # Remove tool requests that never got a response AND tool responses for unmatched requests
    final: list[BaseMessage] = []
    for msg in normalized:
        if isinstance(msg, AIMessage):
            if msg.tool_calls:
                # Keep only matched tool calls
                matched_calls = [
                    tc
                    for tc in msg.tool_calls
                    if (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)) in matched_request_ids
                ]
                if matched_calls or msg.content:
                    cloned = msg.model_copy(deep=True)
                    cloned.tool_calls = matched_calls
                    final.append(cloned)
            else:
                final.append(msg)

        elif isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id and tc_id in matched_request_ids:
                final.append(msg)

        else:
            final.append(msg)

    # Remove empty messages (no content and no tool calls)
    final = [msg for msg in final if msg.content or (hasattr(msg, "tool_calls") and msg.tool_calls)]

    if removed_invalid_requests > 0 or removed_invalid_responses > 0:
        logger.warning(
            "[ProviderSafety] Normalized tool messages before LLM call: "
            f"removed {removed_invalid_requests} invalid requests, "
            f"{removed_invalid_responses} invalid responses, "
            f"{len(working)} → {len(final)} messages"
        )

    return final


__all__ = [
    "normalize_messages",
]
