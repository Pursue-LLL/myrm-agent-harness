"""Remote sandbox live thread actor endpoint.

Manages physical in-memory conversation state on remote sandbox execution
environments, handling physical thread replacements upon compaction signals.

[INPUT]
- runtime.context.live_thread_compaction_types::CompactionSyncStatus, LiveThreadCompactionResult,
  LiveThreadCompactionSignal, RemoteThreadSnapshot (POS: Data types and protocol models for remote sandbox
  live thread physical compaction.)

[OUTPUT]
- RemoteThreadActorEndpoint: Actor endpoint maintaining the physical live thread inside a remote sandbox.

[POS]
Remote sandbox live thread actor endpoint.
"""

from __future__ import annotations

import time

from myrm_agent_harness.runtime.context.live_thread_compaction_types import (
    CompactionSyncStatus,
    LiveThreadCompactionResult,
    LiveThreadCompactionSignal,
    RemoteThreadSnapshot,
)


class RemoteThreadActorEndpoint:
    """Actor endpoint maintaining the physical live thread inside a remote sandbox."""

    def __init__(self, thread_id: str, tokens_per_char: float = 0.25) -> None:
        self.thread_id = thread_id
        self._tokens_per_char = max(tokens_per_char, 0.05)
        self._messages: list[str] = []
        self._last_applied_sequence: int = 0
        self._is_compacted: bool = False

    @property
    def total_turns(self) -> int:
        """Total message turns currently preserved in physical memory."""
        return len(self._messages)

    @property
    def active_token_count(self) -> int:
        """Physical token usage calculated from current live in-memory messages."""
        total_chars = sum(len(msg) for msg in self._messages)
        return int(total_chars * self._tokens_per_char)

    def append_interaction(self, user_turn: str, assistant_turn: str) -> int:
        """Append a bidirectional conversation turn to the physical remote thread.

        Returns the updated total token count of the thread.
        """
        self._messages.append(f"user: {user_turn}")
        self._messages.append(f"assistant: {assistant_turn}")
        return self.active_token_count

    def get_snapshot(self) -> RemoteThreadSnapshot:
        """Capture an immutable snapshot of current physical thread state."""
        return RemoteThreadSnapshot(
            thread_id=self.thread_id,
            total_turns=len(self._messages),
            active_token_count=self.active_token_count,
            last_applied_sequence=self._last_applied_sequence,
            history_messages=tuple(self._messages),
            is_compacted=self._is_compacted,
        )

    def apply_physical_compaction(
        self, signal: LiveThreadCompactionSignal
    ) -> LiveThreadCompactionResult:
        """Atomically compact the physical remote thread in response to a host signal.

        Replaces the historical bulk of messages with the structured summary,
        preserves specified verbatim tail turns, and reports telemetry back to host.
        """
        now = time.time()
        before_tokens = self.active_token_count

        # 1. Reject stale or reordered synchronization signals
        if signal.sequence_number <= self._last_applied_sequence:
            return LiveThreadCompactionResult(
                status=CompactionSyncStatus.REJECTED_STALE,
                thread_id=self.thread_id,
                sequence_number=signal.sequence_number,
                before_token_count=before_tokens,
                after_token_count=before_tokens,
                compression_ratio=0.0,
                drift_percentage=0.0,
                ack_timestamp=now,
                error_message=(
                    f"Stale sequence {signal.sequence_number} <= {self._last_applied_sequence}"
                ),
                applied_summary=None,
            )

        # 2. Preserve backup in case of internal failure
        backup_messages = list(self._messages)

        try:
            # 3. Physically reconstruct the remote thread
            new_thread: list[str] = [f"[COMPACTED_SUMMARY]\n{signal.compacted_summary}"]
            new_thread.extend(signal.retained_tail_turns)

            self._messages = new_thread
            self._is_compacted = True
            self._last_applied_sequence = signal.sequence_number

            after_tokens = self.active_token_count
            diff = max(before_tokens - after_tokens, 0)
            ratio = float(diff / before_tokens) if before_tokens > 0 else 0.0

            # 4. Measure token drift against expected host target budget
            target = signal.target_token_budget
            if target > 0:
                drift = abs(after_tokens - target) / float(target)
            else:
                drift = 0.0

            status = (
                CompactionSyncStatus.SUCCESS
                if drift <= 0.05
                else CompactionSyncStatus.PARTIAL_DRIFT
            )

            return LiveThreadCompactionResult(
                status=status,
                thread_id=self.thread_id,
                sequence_number=signal.sequence_number,
                before_token_count=before_tokens,
                after_token_count=after_tokens,
                compression_ratio=ratio,
                drift_percentage=drift,
                ack_timestamp=now,
                error_message=None,
                applied_summary=signal.compacted_summary,
            )
        except Exception as exc:
            # Rollback to pre-compaction state on catastrophic error
            self._messages = backup_messages
            return LiveThreadCompactionResult(
                status=CompactionSyncStatus.FAILED_ROLLBACK,
                thread_id=self.thread_id,
                sequence_number=signal.sequence_number,
                before_token_count=before_tokens,
                after_token_count=self.active_token_count,
                compression_ratio=0.0,
                drift_percentage=1.0,
                ack_timestamp=now,
                error_message=f"Compaction failed: {exc}",
                applied_summary=None,
            )
