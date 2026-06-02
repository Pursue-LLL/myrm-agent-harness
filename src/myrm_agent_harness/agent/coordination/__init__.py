"""Subagent coordination primitives (teammate mailbox)."""

from .mailbox import (
    TeammateMailbox,
    drain_teammate_messages_for_task,
    emit_teammate_message_sse,
    format_roster_prompt,
    format_teammate_injection,
    get_last_drained_messages,
    get_teammate_mailbox,
    group_history_by_task,
    list_teammate_history,
    register_active_teammate,
    unregister_active_teammate,
)
from .types import TeammateMessage, TeammateSendResult

__all__ = [
    "TeammateMailbox",
    "TeammateMessage",
    "TeammateSendResult",
    "drain_teammate_messages_for_task",
    "emit_teammate_message_sse",
    "format_roster_prompt",
    "format_teammate_injection",
    "get_last_drained_messages",
    "get_teammate_mailbox",
    "group_history_by_task",
    "list_teammate_history",
    "register_active_teammate",
    "unregister_active_teammate",
]
