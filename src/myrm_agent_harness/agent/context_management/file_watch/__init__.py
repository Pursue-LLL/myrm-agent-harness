"""Package facade for file watch.

[INPUT]
- agent.context_management.file_watch.file_watch_types::AutoIngressResult, ContextInvalidationNudge,
  DocumentFreshnessStatus, FileFingerprint, FileMutationKind, SessionDocumentBinding (POS: Types and models
  for file watch.)
- agent.context_management.file_watch.workspace_file_watch_gateway::WorkspaceFileWatchContextGateway (POS:
  Gateway orchestrating workspace file mutation events and session context invalidation.)

[OUTPUT]
- Re-exports: AutoIngressResult, ContextInvalidationNudge, DocumentFreshnessStatus, FileFingerprint,
  FileMutationKind, SessionDocumentBinding, WorkspaceFileWatchContextGateway

[POS]
Package facade for file watch.
"""

# ============================================================================
# Workspace File Watch Context Invalidation & Auto-Ingress Package (Item 165)
# ============================================================================

from .file_watch_types import (
    AutoIngressResult,
    ContextInvalidationNudge,
    DocumentFreshnessStatus,
    FileFingerprint,
    FileMutationKind,
    SessionDocumentBinding,
)
from .workspace_file_watch_gateway import WorkspaceFileWatchContextGateway

__all__ = [
    "AutoIngressResult",
    "ContextInvalidationNudge",
    "DocumentFreshnessStatus",
    "FileFingerprint",
    "FileMutationKind",
    "SessionDocumentBinding",
    "WorkspaceFileWatchContextGateway",
]
