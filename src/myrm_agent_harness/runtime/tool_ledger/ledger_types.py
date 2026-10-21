"""Strongly typed data contracts for durable tool run ledger and pre-retry reconciliation.

[OUTPUT]
- ToolExecutionStatus: Execution status of an individual tool call (STARTED, SUCCEEDED, FAILED, UNKNOWN).
- ToolRunEntry: Relational record of an executed tool call with preview and artifact pointers.
- ReconciliationActionStatus: Classified state for pre-retry user reconciliation.
- ActionReconciliationItem: Single item in the pre-retry audit receipt.
- PreRetryReconciliationReport: Comprehensive pre-retry action audit report.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- ToolExecutionStatus
- ReconciliationActionStatus
- ToolRunEntry
- ActionReconciliationItem
- PreRetryReconciliationReport

[POS]
Strongly typed data contracts for durable tool run ledger and pre-retry reconciliation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ToolExecutionStatus(StrEnum):
    """Lifecycle state of an individual tool execution in the durable ledger."""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ReconciliationActionStatus(StrEnum):
    """Action classification presented to users prior to triggering a retry."""

    REUSABLE_COMPLETED = "reusable_completed"
    """Action succeeded earlier; cached result will be reused without re-execution or token cost."""

    PENDING_EXECUTION = "pending_execution"
    """Action was planned but never dispatched before the interruption."""

    UNKNOWN_REQUIRES_CONFIRMATION = "unknown_requires_confirmation"
    """Action was in-flight during a crash/disconnect; side effects may have occurred, requiring user ACK."""

    FAILED_NEEDS_RETRY = "failed_needs_retry"
    """Action explicitly failed and is eligible for fresh retry attempt."""


@dataclass(frozen=True)
class ToolRunEntry:
    """Relational record of a single tool invocation stored in the durable ledger."""

    call_id: str
    tool_name: str
    arguments_json: str
    status: ToolExecutionStatus
    result_preview: str = ""
    artifact_id: str | None = None
    is_external_side_effect: bool = False
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    duration_ms: float = 0.0


@dataclass(frozen=True)
class ActionReconciliationItem:
    """Individual tool call status audited for pre-retry safety."""

    call_id: str
    tool_name: str
    arguments_json: str
    reconciliation_status: ReconciliationActionStatus
    can_auto_resume: bool
    user_guidance: str


@dataclass(frozen=True)
class PreRetryReconciliationReport:
    """Actionable pre-retry report presented in UI before resuming an interrupted turn."""

    session_id: str
    task_id: str
    items: tuple[ActionReconciliationItem, ...]
    safe_to_auto_resume: bool
    completed_reused_count: int
    pending_count: int
    unknown_danger_count: int
    failed_count: int
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def assemble(
        cls,
        session_id: str,
        task_id: str,
        items: list[ActionReconciliationItem] | tuple[ActionReconciliationItem, ...],
    ) -> PreRetryReconciliationReport:
        """Assemble items and calculate safety thresholds for automated resume."""
        c_count = sum(
            1 for i in items if i.reconciliation_status == ReconciliationActionStatus.REUSABLE_COMPLETED
        )
        p_count = sum(
            1 for i in items if i.reconciliation_status == ReconciliationActionStatus.PENDING_EXECUTION
        )
        u_count = sum(
            1 for i in items if i.reconciliation_status == ReconciliationActionStatus.UNKNOWN_REQUIRES_CONFIRMATION
        )
        f_count = sum(
            1 for i in items if i.reconciliation_status == ReconciliationActionStatus.FAILED_NEEDS_RETRY
        )
        # Any UNKNOWN action with external side effects requires explicit user confirmation
        is_safe = u_count == 0

        return cls(
            session_id=session_id,
            task_id=task_id,
            items=tuple(items),
            safe_to_auto_resume=is_safe,
            completed_reused_count=c_count,
            pending_count=p_count,
            unknown_danger_count=u_count,
            failed_count=f_count,
        )
