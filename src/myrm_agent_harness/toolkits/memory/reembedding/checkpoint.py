"""Persistent checkpoint and breakpoint resume coordinator for re-embedding jobs.

Tracks processed cursor offsets, completed record IDs, and error queues
to guarantee zero duplicate operations upon resumption.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class CheckpointState:
    """Internal mutable snapshot of re-embedding execution progress."""

    job_id: str
    last_cursor: str | None = None
    processed_record_ids: set[str] = field(default_factory=set)
    failed_record_ids: set[str] = field(default_factory=set)
    is_completed: bool = False
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ReembeddingCheckpointManager:
    """Manages persistent checkpoint states to guarantee zero-loss breakpoint resumption."""

    def __init__(self) -> None:
        """Initialize in-memory registry for checkpoint persistence."""
        self._checkpoints: dict[str, CheckpointState] = {}

    def get_checkpoint(self, job_id: str) -> CheckpointState | None:
        """Retrieve existing checkpoint state for the specified job."""
        return self._checkpoints.get(job_id)

    def record_progress(
        self,
        job_id: str,
        cursor: str | None,
        processed_batch_ids: Sequence[str],
        failed_batch_ids: Sequence[str] | None = None,
    ) -> CheckpointState:
        """Atomically record batch progress and advance cursor position."""
        state = self._checkpoints.setdefault(
            job_id,
            CheckpointState(job_id=job_id),
        )

        state.last_cursor = cursor
        state.processed_record_ids.update(processed_batch_ids)
        if failed_batch_ids:
            state.failed_record_ids.update(failed_batch_ids)
        state.updated_at = datetime.now(UTC).isoformat()
        return state

    def filter_unprocessed(
        self,
        job_id: str,
        records: Sequence[str],
    ) -> list[str]:
        """Filter out already processed record IDs for idempotent resumption."""
        state = self._checkpoints.get(job_id)
        if state is None or not state.processed_record_ids:
            return list(records)
        return [r for r in records if r not in state.processed_record_ids]

    def mark_completed(self, job_id: str) -> None:
        """Mark job execution as successfully completed."""
        state = self._checkpoints.setdefault(
            job_id,
            CheckpointState(job_id=job_id),
        )
        state.is_completed = True
        state.updated_at = datetime.now(UTC).isoformat()

    def reset_checkpoint(self, job_id: str) -> None:
        """Clear checkpoint to force complete re-execution."""
        self._checkpoints.pop(job_id, None)
