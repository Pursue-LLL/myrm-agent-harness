"""Types and models for branch run.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- RunStatus: Execution status lifecycle of a durable BranchRun.
- PolicySnapshot: Immutable execution policy snapshot captured at fork time.
- IntentSnapshot: Immutable user intent and objective snapshot captured at fork time.
- RunAttempt: Individual execution attempt preserving complete audit trial and telemetry.
- BranchRun: Independent first-class Run entity derived from a session DAG fork point.
- ArtifactDiffItem: Single artifact mutation comparison between two branch runs.
- BranchArtifactComparison: Comprehensive cross-branch artifact inspection report.

[POS]
Types and models for branch run.
"""

# ============================================================================
# BranchRun & Immutable Policy Snapshot Types (Item 152)
# Strict typed contracts for dual-branching session forks, immutable policy
# snapshots, durable attempt ledgers, and cross-branch artifact comparisons.
# ============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class RunStatus(StrEnum):
    """Execution status lifecycle of a durable BranchRun."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass(slots=True, frozen=True)
class PolicySnapshot:
    """Immutable execution policy snapshot captured at fork time."""

    model_name: str
    temperature: float = 0.7
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)
    sandbox_mode: str = "sandboxed_bwrap"
    timeout_seconds: int = 600
    custom_flags: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, str | float | int | list[str] | list[list[str]]]:
        """Serializes policy snapshot to dictionary."""
        return {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "allowed_tools": list(self.allowed_tools),
            "sandbox_mode": self.sandbox_mode,
            "timeout_seconds": self.timeout_seconds,
            "custom_flags": [list(item) for item in self.custom_flags],
        }


@dataclass(slots=True, frozen=True)
class IntentSnapshot:
    """Immutable user intent and objective snapshot captured at fork time."""

    user_prompt: str
    objective_summary: str
    prior_artifact_ids: tuple[str, ...] = field(default_factory=tuple)
    captured_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | float | list[str]]:
        """Serializes intent snapshot to dictionary."""
        return {
            "user_prompt": self.user_prompt,
            "objective_summary": self.objective_summary,
            "prior_artifact_ids": list(self.prior_artifact_ids),
            "captured_at": self.captured_at,
        }


@dataclass(slots=True)
class RunAttempt:
    """Individual execution attempt preserving complete audit trial and telemetry."""

    attempt_id: str
    attempt_number: int
    tool_call_count: int
    duration_ms: float
    status: RunStatus
    error_message: str = ""
    thought_trace: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | int | float]:
        """Serializes run attempt to dictionary."""
        return {
            "attempt_id": self.attempt_id,
            "attempt_number": self.attempt_number,
            "tool_call_count": self.tool_call_count,
            "duration_ms": self.duration_ms,
            "status": str(self.status),
            "error_message": self.error_message,
            "thought_trace": self.thought_trace,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class BranchRun:
    """Independent first-class Run entity derived from a session DAG fork point."""

    run_id: str
    session_id: str
    parent_run_id: str | None
    fork_node_id: str | None
    policy_snapshot: PolicySnapshot
    intent_snapshot: IntentSnapshot
    status: RunStatus = RunStatus.PENDING
    attempt_history: list[RunAttempt] = field(default_factory=list)
    generated_artifact_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, str | float | None | list[str] | dict[str, object] | list[dict[str, object]]]:
        """Serializes branch run entity to dictionary."""
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "parent_run_id": self.parent_run_id,
            "fork_node_id": self.fork_node_id,
            "policy_snapshot": self.policy_snapshot.to_dict(),
            "intent_snapshot": self.intent_snapshot.to_dict(),
            "status": str(self.status),
            "attempt_history": [a.to_dict() for a in self.attempt_history],
            "generated_artifact_ids": list(self.generated_artifact_ids),
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


@dataclass(slots=True)
class ArtifactDiffItem:
    """Single artifact mutation comparison between two branch runs."""

    artifact_id: str
    change_type: str  # "ADDED", "REMOVED", "MODIFIED", "IDENTICAL"
    diff_details: str = ""

    def to_dict(self) -> dict[str, str]:
        """Serializes artifact diff item to dictionary."""
        return {
            "artifact_id": self.artifact_id,
            "change_type": self.change_type,
            "diff_details": self.diff_details,
        }


@dataclass(slots=True)
class BranchArtifactComparison:
    """Comprehensive cross-branch artifact inspection report."""

    source_run_id: str
    target_run_id: str
    common_artifact_count: int
    divergent_artifacts: list[ArtifactDiffItem] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, str | int | list[dict[str, str]]]:
        """Serializes comparison report to dictionary."""
        return {
            "source_run_id": self.source_run_id,
            "target_run_id": self.target_run_id,
            "common_artifact_count": self.common_artifact_count,
            "divergent_artifacts": [d.to_dict() for d in self.divergent_artifacts],
            "summary": self.summary,
        }
