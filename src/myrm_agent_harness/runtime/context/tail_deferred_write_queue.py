"""Tail-only context append and deferred write queue.

Ensures that provider context grows strictly at the tail across sequential requests,
staging asynchronous or external messages in a FIFO queue until step checkpoints,
thereby guaranteeing prefix KV cache stability and causal consistency.

[INPUT]
- runtime.context.append_only_compaction_types::ContextEntryRole, ContextLogEntry (POS: Types for
  append-only compaction ledger and atomic tool-pair cut-point engine.)
- runtime.context.tail_deferred_overflow_types::DeferredMessageEntry, DeferredWritePriority (POS: Tail-only
  context append and disambiguated overflow types.)

[OUTPUT]
- TailDeferredWriteQueue: Queue for buffering external messages and appending them at checkpoints.

[POS]
Tail-only context append and deferred write queue.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence

from .append_only_compaction_types import ContextEntryRole, ContextLogEntry
from .tail_deferred_overflow_types import DeferredMessageEntry, DeferredWritePriority


class TailDeferredWriteQueue:
    """Queue for buffering external messages and appending them at checkpoints."""

    def __init__(self) -> None:
        self._staged: list[DeferredMessageEntry] = []
        self._applied_history: list[DeferredMessageEntry] = []
        self._counter: int = 0

    def stage_deferred(
        self,
        role: str,
        content: str,
        priority: DeferredWritePriority = DeferredWritePriority.NORMAL,
        metadata: Mapping[str, str] | None = None,
    ) -> DeferredMessageEntry:
        """Stage an external message without mutating active context."""
        self._counter += 1
        entry_id = f"def_{self._counter}_{uuid.uuid4().hex[:8]}"
        staged_entry = DeferredMessageEntry(
            entry_id=entry_id,
            role=role,
            content=content,
            priority=priority,
            metadata=dict(metadata or {}),
            staged_at_ms=int(time.time() * 1000),
        )
        self._staged.append(staged_entry)
        return staged_entry

    def has_pending(self) -> bool:
        """Return True if pending deferred messages exist."""
        return len(self._staged) > 0

    def pending_count(self) -> int:
        """Return count of currently staged messages."""
        return len(self._staged)

    def peek_pending(self) -> list[DeferredMessageEntry]:
        """Return shallow copy of staged messages."""
        return list(self._staged)

    def drain_and_append_at_tail(
        self,
        active_context: Sequence[ContextLogEntry],
        turn_id: int = 0,
    ) -> tuple[list[ContextLogEntry], list[DeferredMessageEntry]]:
        """Apply all staged messages strictly at the tail of active context."""
        if not self._staged:
            return list(active_context), []

        # Sort stably by priority: SYSTEM_ALERT -> HIGH -> NORMAL, preserving FIFO within same priority
        priority_weights = {
            DeferredWritePriority.SYSTEM_ALERT: 0,
            DeferredWritePriority.HIGH: 1,
            DeferredWritePriority.NORMAL: 2,
        }
        sorted_staged = sorted(self._staged, key=lambda item: priority_weights.get(item.priority, 2))

        appended_entries: list[ContextLogEntry] = []
        for staged in sorted_staged:
            role_enum = ContextEntryRole.USER
            if staged.role.upper() == "SYSTEM":
                role_enum = ContextEntryRole.SYSTEM
            elif staged.role.upper() == "ASSISTANT":
                role_enum = ContextEntryRole.ASSISTANT
            elif staged.role.upper() == "TOOL_CALL":
                role_enum = ContextEntryRole.TOOL_CALL
            elif staged.role.upper() == "TOOL_RESULT":
                role_enum = ContextEntryRole.TOOL_RESULT

            entry = ContextLogEntry(
                entry_id=staged.entry_id,
                role=role_enum,
                content=staged.content,
                tool_call_id=None,
                token_estimate=max(1, len(staged.content) // 4),
                turn_id=turn_id,
                metadata={
                    **staged.metadata,
                    "deferred_priority": staged.priority.value,
                    "staged_at_ms": str(staged.staged_at_ms),
                },
            )
            appended_entries.append(entry)

        updated_context = list(active_context) + appended_entries
        applied = list(sorted_staged)
        self._applied_history.extend(applied)
        self._staged.clear()
        return updated_context, applied

    @staticmethod
    def validate_tail_only_invariant(
        previous_entries: Sequence[ContextLogEntry],
        current_entries: Sequence[ContextLogEntry],
    ) -> bool:
        """Assert that current_entries strictly preserves previous_entries as its exact prefix.

        Guarantees that no elements have been prepended, spliced, or modified in the prefix,
        ensuring model provider KV prefix cache validity.
        """
        if len(current_entries) < len(previous_entries):
            return False

        for i, prev in enumerate(previous_entries):
            curr = current_entries[i]
            if curr.entry_id != prev.entry_id:
                return False
            if curr.role != prev.role:
                return False
            if curr.content != prev.content:
                return False
            if curr.tool_call_id != prev.tool_call_id:
                return False

        return True
