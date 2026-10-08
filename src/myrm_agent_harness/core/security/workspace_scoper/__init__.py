"""Package exports for Workspace Scoper and Cross-Contamination Guard.

[INPUT]
- None.

[OUTPUT]
- WorkspaceContaminationGuard
- WorkspaceAccessMode, FileAccessAction, WorkspaceBinding, FileAccessAuditEntry, WorkspaceAuditReport
- CrossWorkspaceContaminationError, WorkspaceScoperError

[POS]
- Harness core security module for per-task workspace sandboxing and leakage auditing.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.workspace_scoper.guard import (
    WorkspaceContaminationGuard,
)
from myrm_agent_harness.core.security.workspace_scoper.types import (
    CrossWorkspaceContaminationError,
    FileAccessAction,
    FileAccessAuditEntry,
    WorkspaceAccessMode,
    WorkspaceAuditReport,
    WorkspaceBinding,
    WorkspaceScoperError,
)

__all__ = [
    "CrossWorkspaceContaminationError",
    "FileAccessAction",
    "FileAccessAuditEntry",
    "WorkspaceAccessMode",
    "WorkspaceAuditReport",
    "WorkspaceBinding",
    "WorkspaceContaminationGuard",
    "WorkspaceScoperError",
]
