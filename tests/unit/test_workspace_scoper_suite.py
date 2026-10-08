"""Unit tests for Per-Task Workspace Scoping and Cross-Contamination Guard suite.

[POS]
Harness core security test suite verifying task directory isolation,
strict scoping containment, mode toggling, and file access audit reporting.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from myrm_agent_harness.core.security.workspace_scoper import (
    CrossWorkspaceContaminationError,
    FileAccessAction,
    WorkspaceAccessMode,
    WorkspaceContaminationGuard,
)


def test_workspace_binding_and_containment() -> None:
    guard = WorkspaceContaminationGuard()

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_dir = os.path.join(tmpdir, "invoices")
        os.makedirs(workspace_dir, exist_ok=True)

        binding = guard.bind_task_workspace(
            task_id="task_inv_101",
            workspace_root=workspace_dir,
            access_mode=WorkspaceAccessMode.SCOPED_STRICT,
        )

        assert binding.task_id == "task_inv_101"
        assert binding.workspace_root == os.path.abspath(workspace_dir)
        assert binding.access_mode == WorkspaceAccessMode.SCOPED_STRICT

        # Allowed read inside workspace
        file_path = os.path.join(workspace_dir, "2026_q3.pdf")
        assert guard.verify_path_access("task_inv_101", file_path, FileAccessAction.READ) is True

        # Allowed write inside workspace
        out_csv = os.path.join(workspace_dir, "summary.csv")
        assert guard.verify_path_access("task_inv_101", out_csv, FileAccessAction.WRITE) is True

        report = guard.generate_audit_report("task_inv_101")
        assert report.total_accesses == 2
        assert report.violations_count == 0
        assert os.path.abspath(out_csv) in report.modified_files


def test_strict_scoping_blocks_cross_contamination() -> None:
    guard = WorkspaceContaminationGuard()

    with tempfile.TemporaryDirectory() as tmpdir:
        task_dir = os.path.join(tmpdir, "task_alpha")
        other_dir = os.path.join(tmpdir, "task_beta_confidential")
        os.makedirs(task_dir, exist_ok=True)
        os.makedirs(other_dir, exist_ok=True)

        guard.bind_task_workspace("task_alpha", task_dir)

        # Attempt to access another task's directory
        forbidden_file = os.path.join(other_dir, "secret_payroll.xlsx")
        with pytest.raises(CrossWorkspaceContaminationError) as exc_info:
            guard.verify_path_access("task_alpha", forbidden_file, FileAccessAction.READ)

        assert exc_info.value.task_id == "task_alpha"
        assert os.path.abspath(task_dir) in str(exc_info.value)

        # Attempt directory traversal escape
        traversal_path = os.path.join(task_dir, "..", "task_beta_confidential", "secret_payroll.xlsx")
        with pytest.raises(CrossWorkspaceContaminationError):
            guard.verify_path_access("task_alpha", traversal_path, FileAccessAction.READ)

        # Check violation logged in audit report
        report = guard.generate_audit_report("task_alpha")
        assert report.violations_count == 2
        assert len(report.audit_entries) == 2
        assert all(not e.allowed for e in report.audit_entries)


def test_full_system_access_mode_toggle() -> None:
    guard = WorkspaceContaminationGuard()

    with tempfile.TemporaryDirectory() as tmpdir:
        task_dir = os.path.join(tmpdir, "task_work")
        system_dir = os.path.join(tmpdir, "system_libs")
        os.makedirs(task_dir, exist_ok=True)
        os.makedirs(system_dir, exist_ok=True)

        guard.bind_task_workspace("task_full", task_dir, WorkspaceAccessMode.SCOPED_STRICT)

        sys_file = os.path.join(system_dir, "dataset.parquet")

        # In strict mode, blocked
        with pytest.raises(CrossWorkspaceContaminationError):
            guard.verify_path_access("task_full", sys_file, FileAccessAction.READ)

        # Toggle to full system access
        updated = guard.update_access_mode("task_full", WorkspaceAccessMode.FULL_SYSTEM_ACCESS)
        assert updated.access_mode == WorkspaceAccessMode.FULL_SYSTEM_ACCESS

        # Now permitted
        assert guard.verify_path_access("task_full", sys_file, FileAccessAction.READ) is True

        report = guard.generate_audit_report("task_full")
        assert report.total_accesses == 2
        assert report.violations_count == 1  # 1 blocked before toggle, 1 allowed after


def test_missing_task_binding_error() -> None:
    guard = WorkspaceContaminationGuard()

    with pytest.raises(KeyError):
        guard.verify_path_access("unregistered_task", "/tmp/file.txt", FileAccessAction.READ)

    with pytest.raises(KeyError):
        guard.update_access_mode("unregistered_task", WorkspaceAccessMode.FULL_SYSTEM_ACCESS)

    with pytest.raises(KeyError):
        guard.generate_audit_report("unregistered_task")
