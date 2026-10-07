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
