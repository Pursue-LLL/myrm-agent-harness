"""
[POS] src/myrm_agent_harness/core/security/host_execution_guard/facade.py
[INPUT] typing
[OUTPUT] HostExecutionGuardSuite

Unified facade for Local Host Safe Execution Sandbox & Non-Destructive Guardrail Suite.
Integrates path protection/overlay, destructive command AST inspection, and workspace COW undo vault.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .destructive_ast_guard import DestructiveCommandASTGuard
from .path_shield_overlay import PathShieldOverlay
from .types import (
    CommandInspectionResult,
    DestructiveRiskLevel,
    HostExecutionGuardMetrics,
    PathAccessMode,
    PathInspectionResult,
    PathProtectionAction,
    WorkspaceSnapshot,
)
from .workspace_cow_vault import WorkspaceCowVault

logger = logging.getLogger(__name__)


class HostExecutionGuardSuite:
    """Unified security facade coordinating host path shielding, command safety, and COW rollback."""

    def __init__(
        self,
        workspace_root: str | None = None,
        scratch_overlay_dir: str | None = None,
        custom_protected_paths: tuple[str, ...] | None = None,
    ) -> None:
        self._path_shield = PathShieldOverlay(
            workspace_root=workspace_root,
            scratch_overlay_dir=scratch_overlay_dir,
            custom_protected_paths=custom_protected_paths,
        )
        self._ast_guard = DestructiveCommandASTGuard()
        self._cow_vault = WorkspaceCowVault()
        self._metrics = HostExecutionGuardMetrics()

    @property
    def metrics(self) -> HostExecutionGuardMetrics:
        """Cumulative operational metrics."""
        return self._metrics

    @property
    def workspace_root(self) -> str | None:
        """Active workspace root directory."""
        return self._path_shield.workspace_root

    @property
    def scratch_overlay_dir(self) -> str | None:
        """Active scratch overlay staging directory."""
        return self._path_shield.scratch_overlay_dir

    def inspect_path(
        self,
        target_path: str,
        mode: PathAccessMode = PathAccessMode.WRITE,
    ) -> PathInspectionResult:
        """Inspect target path access against system protection rules and determine redirection."""
        self._metrics.paths_inspected_total += 1
        res = self._path_shield.inspect_path(target_path=target_path, mode=mode)

        if res.action == PathProtectionAction.VIRTUAL_OVERLAY:
            self._metrics.paths_redirected_total += 1
        elif res.action == PathProtectionAction.BLOCK:
            self._metrics.paths_blocked_total += 1

        return res

    def inspect_command(self, command: str) -> CommandInspectionResult:
        """Inspect shell command string for catastrophic or high-risk execution patterns."""
        self._metrics.commands_inspected_total += 1
        res = self._ast_guard.inspect_command(command=command)

        if res.risk_level == DestructiveRiskLevel.BLOCKED_DESTRUCTIVE:
            self._metrics.commands_blocked_total += 1
        elif res.risk_level == DestructiveRiskLevel.REQUIRE_HITL:
            self._metrics.hitl_requested_total += 1

        return res

    def approve_command(self, inspection_id: str) -> CommandInspectionResult:
        """User confirms and approves a pending high-risk command execution ticket."""
        res = self._ast_guard.approve_command(inspection_id=inspection_id)
        self._metrics.hitl_approved_total += 1
        return res

    def reject_command(self, inspection_id: str) -> CommandInspectionResult:
        """User explicitly rejects a pending high-risk command ticket."""
        return self._ast_guard.reject_command(inspection_id=inspection_id)

    def list_pending_commands(self) -> list[CommandInspectionResult]:
        """List all commands currently awaiting operator approval."""
        return self._ast_guard.list_pending_approvals()

    def create_workspace_snapshot(
        self,
        workspace_root: str,
        target_rel_paths: tuple[str, ...],
        description: str = "Pre-modification checkpoint",
    ) -> WorkspaceSnapshot:
        """Capture pre-modification state of specified files within the workspace root."""
        self._metrics.snapshots_created_total += 1
        return self._cow_vault.create_snapshot(
            workspace_root=workspace_root,
            target_rel_paths=target_rel_paths,
            description=description,
        )

    def rollback_workspace_snapshot(self, snapshot_id: str) -> WorkspaceSnapshot:
        """Atomically restore workspace files to the recorded snapshot state."""
        self._metrics.rollbacks_executed_total += 1
        return self._cow_vault.rollback_snapshot(snapshot_id=snapshot_id)

    def get_snapshot(self, snapshot_id: str) -> WorkspaceSnapshot:
        """Fetch snapshot descriptor by ID."""
        return self._cow_vault.get_snapshot(snapshot_id=snapshot_id)

    def list_snapshots(self) -> list[WorkspaceSnapshot]:
        """List all tracked workspace snapshots."""
        return self._cow_vault.list_snapshots()
