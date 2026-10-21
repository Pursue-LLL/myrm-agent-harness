"""Message priority classification for intelligent compression.

吸收OpenSpace conversation_formatter的6级优先级理念，简化为4级：
- CRITICAL (0-1): Human messages + Final iteration content
- HIGH (2): Tool calls + Tool errors (paired)
- MEDIUM (3): Assistant reasoning + Tool results with summary
- LOW (4): Tool success results

References:
- OpenSpace: conversation_formatter.py (6-level priority)
- Onyx: compression.py (no priority, LLM-based)

[INPUT]
- (none)

[OUTPUT]
- MessagePriority: Outbound message priority (lower value = higher priority).
- classify_message_priority: Classify a message's priority for compression.

[POS]
Message priority classification for intelligent compression.
"""

from __future__ import annotations

from enum import IntEnum

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


class MessagePriority(IntEnum):
    """Message priority levels for compression.

    Lower values = higher priority (kept longer during compression).
    """

    CRITICAL_USER = 0  # Human messages - NEVER compress
    CRITICAL_FINAL = 1  # Final iteration content - NEVER compress
    HIGH_TOOL_CALL = 2  # Tool calls - keep paired with errors
    HIGH_TOOL_ERROR = 2  # Tool errors - same priority as calls
    MEDIUM_REASONING = 3  # Assistant reasoning
    MEDIUM_TOOL_SUMMARY = 3  # Tool results with embedded summary
    LOW_TOOL_SUCCESS = 4  # Tool success results - first to compress


def classify_message_priority(
    msg: BaseMessage, is_last_iteration: bool = False, failed_tool_call_ids: frozenset[str] | None = None
) -> MessagePriority:
    """Classify a message's priority for compression.

    Args:
        msg: Message to classify
        is_last_iteration: Whether this is the final iteration (affects assistant priority)
        failed_tool_call_ids: Structured failed tool-call IDs that should be preserved longer

    Returns:
        Priority level
    """
    protected_tool_calls = failed_tool_call_ids or frozenset()

    # Human messages are always critical
    if isinstance(msg, HumanMessage):
        return MessagePriority.CRITICAL_USER

    # AI messages (assistant reasoning)
    if isinstance(msg, AIMessage):
        # Tool calls are high priority (paired with results/errors)
        if msg.tool_calls:
            return MessagePriority.HIGH_TOOL_CALL
        # Final iteration content is critical
        if is_last_iteration and msg.content:
            return MessagePriority.CRITICAL_FINAL
        # Non-final reasoning is medium
        return MessagePriority.MEDIUM_REASONING

    # Tool messages
    if isinstance(msg, ToolMessage):
        if msg.tool_call_id and msg.tool_call_id in protected_tool_calls:
            return MessagePriority.HIGH_TOOL_ERROR
        # Error results are high priority (paired with calls)
        if _is_tool_error(msg):
            return MessagePriority.HIGH_TOOL_ERROR
        # Results with embedded summary are medium
        if _has_embedded_summary(msg):
            return MessagePriority.MEDIUM_TOOL_SUMMARY
        # Success results are low priority
        return MessagePriority.LOW_TOOL_SUCCESS

    # Default: medium priority
    return MessagePriority.MEDIUM_REASONING


def _is_tool_error(msg: ToolMessage) -> bool:
    """Detect if tool message is an error.

    Borrowed from OpenSpace conversation_formatter.py:296-310
    """
    content = str(msg.content)
    if not content:
        return False

    head = content[:200].lower()
    return (
        content.startswith("[ERROR]")
        or content.startswith("ERROR")
        or "error" in head[:50]
        or "task failed" in head
        or "connection refused" in head
        or "timed out" in head
        or "traceback" in head
    )


def _has_embedded_summary(msg: ToolMessage) -> bool:
    """Check if tool result has self-generated summary.

    Shell agent and other tools may include "Execution Summary" blocks.
    Borrowed from OpenSpace conversation_formatter.py:313-334
    """
    import re

    content = str(msg.content)
    return bool(re.search(r"(Execution Summary \(\d+ steps?\):.*?)(?:={10,}|$)", content, re.DOTALL))
