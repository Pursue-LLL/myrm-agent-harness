"""Type definitions for Per-Task Workspace Scoping and Cross-Contamination Guard.

[INPUT]
- None.

[OUTPUT]
- WorkspaceAccessMode, FileAccessAction
- WorkspaceBinding, FileAccessAuditEntry, WorkspaceAuditReport
- CrossWorkspaceContaminationError, WorkspaceScoperError

[POS]
- Harness core security module inspired by WorkBuddy task workspace sandboxing.
- Isolates file system access on a per-task basis, preventing cross-contamination
  between sensitive business materials (invoices, contracts, code repositories).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class WorkspaceAccessMode(StrEnum):
    """Enforcement mode for file system access boundaries."""

    SCOPED_STRICT = "scoped_strict"  # Default strict mode: access locked within task workspace
    FULL_SYSTEM_ACCESS = "full_system_access"  # Explicitly authorized mode: permits system-wide access


class FileAccessAction(StrEnum):
    """Operation types on the file system."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    LIST = "list"


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    """Binding specification between a task and its isolated directory root."""

    task_id: str
    workspace_root: str
    access_mode: WorkspaceAccessMode = WorkspaceAccessMode.SCOPED_STRICT
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class FileAccessAuditEntry:
    """Audit log entry capturing a file system access event or violation."""

    entry_id: str
    task_id: str
    target_path: str
    action: FileAccessAction
    allowed: bool
    violation_reason: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class WorkspaceAuditReport:
    """Consolidated audit report of task workspace activities and containment integrity."""

    task_id: str
    workspace_root: str
    access_mode: WorkspaceAccessMode
    total_accesses: int
    violations_count: int
    modified_files: tuple[str, ...]
    audit_entries: tuple[FileAccessAuditEntry, ...]
    generated_at: float = field(default_factory=time.time)


class WorkspaceScoperError(Exception):
    """Base exception for workspace scoping and isolation operations."""


class CrossWorkspaceContaminationError(WorkspaceScoperError):
    """Raised when an operation attempts to access a path outside the task workspace scope."""

    def __init__(self, task_id: str, attempted_path: str, workspace_root: str) -> None:
        super().__init__(
            f"Cross-workspace contamination blocked for task '{task_id}': "
            f"Attempted access to '{attempted_path}' outside authorized workspace '{workspace_root}'."
        )
        self.task_id = task_id
        self.attempted_path = attempted_path
        self.workspace_root = workspace_root
