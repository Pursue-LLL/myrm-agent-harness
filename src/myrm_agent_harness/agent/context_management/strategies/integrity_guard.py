"""Tool pair integrity guard for compacted message histories.

Ensures every retained AI tool call keeps a matching ToolMessage, removes
orphan ToolMessages, and trims partially matched multi-tool AI messages
without discarding unrelated conversational content.

[INPUT]
- (none)

[OUTPUT]
- ensure_tool_pair_integrity: Return a structurally valid message list for provider/too...

[POS]
Tool pair integrity guard for compacted message histories.
"""

from __future__ import annotations

from collections import defaultdict

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .tool_call_groups import build_tool_call_groups

logger = get_agent_logger(__name__)


def ensure_tool_pair_integrity(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Return a structurally valid message list for provider/tool replay."""
    if not messages:
        return []

    groups = build_tool_call_groups(messages)
    matched_tool_indices = {group.tool_index for group in groups}
    matched_ids_by_ai_index: dict[int, set[str]] = defaultdict(set)
    for group in groups:
        matched_ids_by_ai_index[group.ai_index].add(group.tool_call_id)

    cleaned_messages: list[BaseMessage] = []
    removed_tool_messages = 0
    trimmed_ai_messages = 0
    dropped_ai_messages = 0

    for index, message in enumerate(messages):
        if isinstance(message, ToolMessage):
            if index in matched_tool_indices:
                cleaned_messages.append(message)
            else:
                removed_tool_messages += 1
            continue

        if isinstance(message, AIMessage) and message.tool_calls:
            valid_ids = matched_ids_by_ai_index.get(index, set())
            matched_tool_calls = [
                tool_call
                for tool_call in message.tool_calls
                if (tool_call_id := tool_call.get("id")) and isinstance(tool_call_id, str) and tool_call_id in valid_ids
            ]

            if len(matched_tool_calls) == len(message.tool_calls):
                cleaned_messages.append(message)
                continue

            replacement = _clone_ai_message_with_tool_calls(message, matched_tool_calls)
            if replacement is None:
                dropped_ai_messages += 1
            else:
                trimmed_ai_messages += 1
                cleaned_messages.append(replacement)
            continue

        cleaned_messages.append(message)

    if (
        removed_tool_messages == 0
        and trimmed_ai_messages == 0
        and dropped_ai_messages == 0
        and len(cleaned_messages) == len(messages)
    ):
        return messages

    logger.warning(
        "[IntegrityGuard] normalized tool pairs: removed_tool_messages=%d, trimmed_ai_messages=%d, dropped_ai_messages=%d",
        removed_tool_messages,
        trimmed_ai_messages,
        dropped_ai_messages,
    )
    return cleaned_messages


def _clone_ai_message_with_tool_calls(message: AIMessage, tool_calls: list[dict[str, object]]) -> AIMessage | None:
    """Clone an AI message with a filtered tool-call list."""
    cloned = message.model_copy(deep=True)
    cloned.tool_calls = tool_calls

    if cloned.additional_kwargs:
        cloned.additional_kwargs = {
            key: value for key, value in cloned.additional_kwargs.items() if key != "tool_calls"
        }

    if tool_calls or _message_has_visible_content(cloned):
        return cloned
    return None


def _message_has_visible_content(message: AIMessage) -> bool:
    """Check whether an AI message still carries meaningful non-tool content."""
    content = message.content
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return len(content) > 0
    return bool(content)
