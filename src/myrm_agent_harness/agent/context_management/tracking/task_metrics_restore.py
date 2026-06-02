"""Archive restore metric helpers.

[INPUT]
- tracking.archive_restore::* (POS: archive restore budget and guidance DTOs)
- tracking.task_metric_events::* (POS: restore outcome and block event DTOs)

[OUTPUT]
- TaskMetricsRestoreMixin: restore budget, outcome, and block-event behavior for TaskMetrics.

[POS]
Archive restore metric layer for TaskMetrics.
"""

from datetime import datetime
from threading import Lock
from typing import Literal, Protocol

from .archive_restore import (
    ArchiveRefetchDecision,
    ArchiveRestoreBudgetPolicy,
    ArchiveRestoreGuidance,
    build_archive_restore_guidance,
)
from .task_metric_events import (
    ArchiveRestoreBlockEvent,
    ArchiveRestoreOutcomeEvent,
    ArchiveRestoreResultEvent,
    RefetchEvent,
)


class _TaskMetricsRestoreState(Protocol):
    task_id: str
    refetch_events: list[RefetchEvent]
    archive_restore_outcome_events: list[ArchiveRestoreOutcomeEvent]
    archive_restore_result_events: list[ArchiveRestoreResultEvent]
    archive_restore_block_events: list[ArchiveRestoreBlockEvent]
    archive_restore_budget_policy: ArchiveRestoreBudgetPolicy
    _lock: Lock

    @property
    def archive_refetch_tokens(self) -> int: ...

    @property
    def pruning_backoff_applied(self) -> bool: ...


class TaskMetricsRestoreMixin:
    """Restore-specific TaskMetrics behavior."""

    @property
    def archive_restore_blocked_count(self: _TaskMetricsRestoreState) -> int:
        """Blocked archived context restore attempts from outcome telemetry."""
        return sum(1 for event in self.archive_restore_outcome_events if event.outcome == "blocked")

    @property
    def archive_restore_requested_count(self: _TaskMetricsRestoreState) -> int:
        """Archive restore decisions evaluated for this task."""
        return len(self.archive_restore_outcome_events)

    @property
    def archive_restore_allowed_count(self: _TaskMetricsRestoreState) -> int:
        """Allowed archived context restore attempts."""
        return sum(1 for event in self.archive_restore_outcome_events if event.outcome == "allowed")

    @property
    def archive_restore_blocked_ratio(self: _TaskMetricsRestoreState) -> float:
        """Blocked archive restore decisions divided by evaluated restore decisions."""
        if self.archive_restore_requested_count == 0:
            return 0.0
        return self.archive_restore_blocked_count / self.archive_restore_requested_count

    def archive_refetch_count_for_path(self: _TaskMetricsRestoreState, archive_path: str) -> int:
        """Number of archive refetch events recorded for a specific path."""
        return sum(
            1
            for event in self.refetch_events
            if event.reason == "archive_reference_read" and event.archive_path == archive_path
        )

    def can_record_archive_refetch(
        self: _TaskMetricsRestoreState,
        archive_path: str,
        estimated_tokens: int,
        policy: ArchiveRestoreBudgetPolicy | None = None,
    ) -> ArchiveRefetchDecision:
        """Evaluate per-task archive refetch budget before exposing archived content."""
        active_policy = policy or self.archive_restore_budget_policy
        path_reads = self.archive_refetch_count_for_path(archive_path)
        if path_reads >= active_policy.max_refetches_per_path:
            return ArchiveRefetchDecision(
                is_archive_path=True,
                allowed=False,
                recorded=False,
                reason="archive_refetch_path_budget_exceeded",
                message="Archived context restore blocked because this path reached the per-task read limit.",
                suggested_action="Use a narrower line range or continue from the existing archive summary.",
                guidance=build_archive_restore_guidance(
                    archive_path,
                    reason="archive_refetch_path_budget_exceeded",
                    backoff_adjusted=self.pruning_backoff_applied,
                ),
            )

        projected_tokens = self.archive_refetch_tokens + max(estimated_tokens, 0)
        if projected_tokens > active_policy.max_refetch_tokens:
            return ArchiveRefetchDecision(
                is_archive_path=True,
                allowed=False,
                recorded=False,
                reason="archive_refetch_token_budget_exceeded",
                message="Archived context restore blocked because this task reached the restore token budget.",
                suggested_action="Read a smaller range or ask for a targeted excerpt from the archive.",
                guidance=build_archive_restore_guidance(
                    archive_path,
                    reason="archive_refetch_token_budget_exceeded",
                    backoff_adjusted=self.pruning_backoff_applied,
                ),
            )

        return ArchiveRefetchDecision(is_archive_path=True, allowed=True, recorded=False)

    def record_archive_restore_blocked(
        self: _TaskMetricsRestoreState,
        *,
        reason: str,
        archive_path: str,
        estimated_tokens: int,
        message: str = "",
        suggested_action: str = "",
        guidance: ArchiveRestoreGuidance | None = None,
    ) -> None:
        """Record blocked archive restore details for UX guidance."""
        with self._lock:
            self.archive_restore_block_events.append(
                ArchiveRestoreBlockEvent(
                    timestamp=datetime.now(),
                    reason=reason,
                    archive_path=archive_path,
                    estimated_tokens=max(estimated_tokens, 0),
                    message=message,
                    suggested_action=suggested_action,
                    guidance=guidance or ArchiveRestoreGuidance(reason_label_key=reason),
                )
            )

    def record_archive_restore_outcome(
        self: _TaskMetricsRestoreState,
        *,
        outcome: Literal["allowed", "blocked"],
        archive_path: str,
        estimated_tokens: int,
        reason: str = "",
        recorded: bool = False,
        is_range_read: bool = False,
    ) -> None:
        """Record an archived context restore decision outcome."""
        with self._lock:
            self.archive_restore_outcome_events.append(
                ArchiveRestoreOutcomeEvent(
                    timestamp=datetime.now(),
                    outcome=outcome,
                    reason=reason,
                    archive_path=archive_path,
                    estimated_tokens=max(estimated_tokens, 0),
                    recorded=recorded,
                    is_range_read=is_range_read,
                )
            )

    def record_archive_restore_result(
        self: _TaskMetricsRestoreState,
        *,
        archive_path: str,
        restore_arg: str,
        start_line: int,
        end_line: int,
        restored_line_count: int,
        estimated_tokens: int,
        restored_bytes: int,
    ) -> None:
        """Record successful typed archive restore materialization metadata."""
        with self._lock:
            self.archive_restore_result_events.append(
                ArchiveRestoreResultEvent(
                    timestamp=datetime.now(),
                    archive_path=archive_path,
                    restore_arg=restore_arg,
                    start_line=max(start_line, 1),
                    end_line=max(end_line, 1),
                    restored_line_count=max(restored_line_count, 0),
                    estimated_tokens=max(estimated_tokens, 0),
                    restored_bytes=max(restored_bytes, 0),
                )
            )


__all__ = ["TaskMetricsRestoreMixin"]
