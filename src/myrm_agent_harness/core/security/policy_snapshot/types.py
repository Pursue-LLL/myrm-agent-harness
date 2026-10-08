"""Types and data structures for In-Flight Policy Snapshot Pinning & Non-Silent Drift.

Enforces:
1. Policy snapshot pinning per task lifecycle (prevents silent runtime mutation).
2. Dual-track policy update channels (Soft Update for new tasks vs Emergency Hot Kill).
3. Cryptographic audit configuration lineage.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

JsonScalar = str | int | float | bool | None


class PolicyUpdateChannel(StrEnum):
    """Dual-track channels for policy modification."""

    SOFT_UPDATE = "SOFT_UPDATE"
    EMERGENCY_HOT_KILL = "EMERGENCY_HOT_KILL"


@dataclass(frozen=True)
class ExecutionPolicySnapshot:
    """Immutable snapshot of governance policy pinned to in-flight tasks."""

    snapshot_id: str
    version_number: int
    policy_snapshot_hash: str
    prompt_template_hash: str
    allowed_tools: tuple[str, ...]
    governance_rules: dict[str, JsonScalar]
    created_at: str


@dataclass(frozen=True)
class EmergencyHotKillDirective:
    """Emergency directive immediately blocking specific high-risk tools in-flight."""

    directive_id: str
    revoked_tools: tuple[str, ...]
    reason: str
    issued_at: str
    is_active: bool = True


@dataclass(frozen=True)
class TaskPolicyBinding:
    """Association pinning an execution policy snapshot to a specific running task."""

    task_id: str
    snapshot: ExecutionPolicySnapshot
    bound_at: str


class PolicySnapshotError(Exception):
    """Base exception for policy snapshot and drift management."""


class PolicyDriftViolationError(PolicySnapshotError):
    """Raised when an operation attempts to violate a task's pinned policy bounds."""


class EmergencyHotKillBlockedError(PolicySnapshotError):
    """Raised when an in-flight tool call is intercepted by an active emergency hot-kill."""
