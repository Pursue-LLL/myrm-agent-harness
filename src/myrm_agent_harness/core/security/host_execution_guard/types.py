"""
[POS] src/myrm_agent_harness/core/security/host_execution_guard/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] PathAccessMode, PathProtectionAction, DestructiveRiskLevel, PathInspectionResult, CommandInspectionResult, FileSnapshotEntry, WorkspaceSnapshot, HostExecutionGuardMetrics

Data structures and specifications for Local Host Safe Execution Sandbox & Non-Destructive Guardrail Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PathAccessMode(StrEnum):
    """File access mode being evaluated."""

    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"


class PathProtectionAction(StrEnum):
    """Enforcement action applied to path operations."""

    ALLOW = "ALLOW"
    VIRTUAL_OVERLAY = "VIRTUAL_OVERLAY"
    BLOCK = "BLOCK"


class DestructiveRiskLevel(StrEnum):
    """Safety risk level determined by AST inspection."""

    SAFE = "SAFE"
    REQUIRE_HITL = "REQUIRE_HITL"
    BLOCKED_DESTRUCTIVE = "BLOCKED_DESTRUCTIVE"


@dataclass(frozen=True)
class PathInspectionResult:
    """Evaluation result of path access against host protection rules."""

    original_path: str
    is_protected: bool
    action: PathProtectionAction
    effective_path: str
    explanation: str


@dataclass(frozen=True)
class CommandInspectionResult:
    """Evaluation result of bash/shell command syntax inspection."""

    inspection_id: str
    command: str
    risk_level: DestructiveRiskLevel
    matched_patterns: tuple[str, ...]
    explanation: str
    requires_hitl: bool
    is_blocked: bool


@dataclass(frozen=True)
class FileSnapshotEntry:
    """Captured state of a single workspace file prior to modification."""

    relative_path: str
    original_hash: str
    original_content: str | None
    is_deleted: bool = False


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Atomic copy-on-write snapshot enabling instant rollback."""

    snapshot_id: str
    workspace_root: str
    created_at: float
    entries: tuple[FileSnapshotEntry, ...]
    description: str
    is_restored: bool = False


@dataclass
class HostExecutionGuardMetrics:
    """Cumulative operational metrics for host execution guardrail operations."""

    paths_inspected_total: int = 0
    paths_redirected_total: int = 0
    paths_blocked_total: int = 0
    commands_inspected_total: int = 0
    commands_blocked_total: int = 0
    hitl_requested_total: int = 0
    hitl_approved_total: int = 0
    snapshots_created_total: int = 0
    rollbacks_executed_total: int = 0
