"""
[POS] src/myrm_agent_harness/core/security/host_execution_guard/__init__.py
[INPUT] .facade, .types
[OUTPUT] HostExecutionGuardSuite, PathShieldOverlay, DestructiveCommandASTGuard, WorkspaceCowVault, ...

Local Host Safe Execution Sandbox & Non-Destructive Guardrail Suite.
Protects host filesystem and processes from accidental corruption and catastrophic command execution.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .destructive_ast_guard import DestructiveCommandASTGuard
from .facade import HostExecutionGuardSuite
from .path_shield_overlay import PathShieldOverlay
from .types import (
    CommandInspectionResult,
    DestructiveRiskLevel,
    FileSnapshotEntry,
    HostExecutionGuardMetrics,
    PathAccessMode,
    PathInspectionResult,
    PathProtectionAction,
    WorkspaceSnapshot,
)
from .workspace_cow_vault import WorkspaceCowVault

__all__ = [
    "CommandInspectionResult",
    "DestructiveCommandASTGuard",
    "DestructiveRiskLevel",
    "FileSnapshotEntry",
    "HostExecutionGuardMetrics",
    "HostExecutionGuardSuite",
    "PathAccessMode",
    "PathInspectionResult",
    "PathProtectionAction",
    "PathShieldOverlay",
    "WorkspaceCowVault",
    "WorkspaceSnapshot",
]
