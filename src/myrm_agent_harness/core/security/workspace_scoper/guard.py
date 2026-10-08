"""Workspace Contamination Guard enforcing task-level directory confinement and audit logging.

[INPUT]
- task_id, workspace_root, target_path, FileAccessAction, WorkspaceAccessMode

[OUTPUT]
- True if path access satisfies scoping constraints.
- CrossWorkspaceContaminationError raised if path escapes scoped workspace.
- WorkspaceAuditReport detailing containment integrity and modified files.

[POS]
- Harness core security module inspired by WorkBuddy task directory isolation.
- Guarantees strict containment for task workspaces, preventing cross-task leaks.
"""

from __future__ import annotations

import os
import threading
import uuid

from myrm_agent_harness.core.security.workspace_scoper.types import (
    CrossWorkspaceContaminationError,
    FileAccessAction,
    FileAccessAuditEntry,
    WorkspaceAccessMode,
    WorkspaceAuditReport,
    WorkspaceBinding,
)


class WorkspaceContaminationGuard:
    """Thread-safe controller ensuring file operations remain strictly inside task workspace."""

    def __init__(self) -> None:
        self._bindings: dict[str, WorkspaceBinding] = {}
        self._audit_log: dict[str, list[FileAccessAuditEntry]] = {}
        self._modified_files: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Resolve absolute, canonical path representation."""
        return os.path.abspath(os.path.expanduser(path))

    def bind_task_workspace(
        self,
        task_id: str,
        workspace_root: str,
        access_mode: WorkspaceAccessMode = WorkspaceAccessMode.SCOPED_STRICT,
    ) -> WorkspaceBinding:
        """Bind a task to an isolated directory root with specified access mode."""
        canonical_root = self._normalize_path(workspace_root)
        binding = WorkspaceBinding(
            task_id=task_id,
            workspace_root=canonical_root,
            access_mode=access_mode,
        )
        with self._lock:
            self._bindings[task_id] = binding
            if task_id not in self._audit_log:
                self._audit_log[task_id] = []
            if task_id not in self._modified_files:
                self._modified_files[task_id] = set()
        return binding

    def get_binding(self, task_id: str) -> WorkspaceBinding | None:
        """Retrieve workspace binding for a task."""
        with self._lock:
            return self._bindings.get(task_id)

    def update_access_mode(
        self,
        task_id: str,
        access_mode: WorkspaceAccessMode,
    ) -> WorkspaceBinding:
        """Update containment mode (e.g. switch between strict scoped and full system access)."""
        with self._lock:
            binding = self._bindings.get(task_id)
            if not binding:
                raise KeyError(f"No workspace binding found for task '{task_id}'")
            updated = WorkspaceBinding(
                task_id=binding.task_id,
                workspace_root=binding.workspace_root,
                access_mode=access_mode,
                created_at=binding.created_at,
            )
            self._bindings[task_id] = updated
            return updated

    def verify_path_access(
        self,
        task_id: str,
        target_path: str,
        action: FileAccessAction,
    ) -> bool:
        """Verify whether target_path access is permitted under current task workspace scope.

        Raises:
            KeyError: If task_id is not bound.
            CrossWorkspaceContaminationError: If path violates strict scoping boundary.
        """
        with self._lock:
            binding = self._bindings.get(task_id)
            if not binding:
                raise KeyError(f"No workspace binding found for task '{task_id}'")

        canonical_target = self._normalize_path(target_path)
        canonical_root = binding.workspace_root

        # Check containment
        is_contained = (
            canonical_target == canonical_root
            or canonical_target.startswith(canonical_root + os.sep)
        )

        entry_id = f"aud_{uuid.uuid4().hex[:10]}"

        if binding.access_mode == WorkspaceAccessMode.SCOPED_STRICT and not is_contained:
            violation_msg = (
                f"Path '{canonical_target}' escapes designated workspace '{canonical_root}'"
            )
            entry = FileAccessAuditEntry(
                entry_id=entry_id,
                task_id=task_id,
                target_path=canonical_target,
                action=action,
                allowed=False,
                violation_reason=violation_msg,
            )
            with self._lock:
                self._audit_log[task_id].append(entry)
            raise CrossWorkspaceContaminationError(
                task_id=task_id,
                attempted_path=canonical_target,
                workspace_root=canonical_root,
            )

        # Authorized access
        entry = FileAccessAuditEntry(
            entry_id=entry_id,
            task_id=task_id,
            target_path=canonical_target,
            action=action,
            allowed=True,
        )
        with self._lock:
            self._audit_log[task_id].append(entry)
            if action in (FileAccessAction.WRITE, FileAccessAction.DELETE):
                self._modified_files[task_id].add(canonical_target)

        return True

    def generate_audit_report(self, task_id: str) -> WorkspaceAuditReport:
        """Generate a complete audit dossier of file operations and boundary integrity."""
        with self._lock:
            binding = self._bindings.get(task_id)
            if not binding:
                raise KeyError(f"No workspace binding found for task '{task_id}'")

            entries = list(self._audit_log.get(task_id, []))
            modified = sorted(self._modified_files.get(task_id, set()))

        violations_count = sum(1 for e in entries if not e.allowed)

        return WorkspaceAuditReport(
            task_id=task_id,
            workspace_root=binding.workspace_root,
            access_mode=binding.access_mode,
            total_accesses=len(entries),
            violations_count=violations_count,
            modified_files=tuple(modified),
            audit_entries=tuple(entries),
        )

    def clear_task(self, task_id: str) -> None:
        """Clear memory structures for a completed or archived task."""
        with self._lock:
            self._bindings.pop(task_id, None)
            self._audit_log.pop(task_id, None)
            self._modified_files.pop(task_id, None)
