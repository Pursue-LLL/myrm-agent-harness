"""Public API for Workspace File Access Boundary Guard & Actual Path Link Resolver.

[INPUT]
- Package import declarations.

[OUTPUT]
- Exported classes, enums, exceptions, and resolver guards.

[POS]
- Harness core security module package entrypoint.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.workspace_boundary.guard import (
    WorkspaceFileAccessGuard,
)
from myrm_agent_harness.core.security.workspace_boundary.resolver import (
    ActualPathLinkResolver,
)
from myrm_agent_harness.core.security.workspace_boundary.types import (
    FileAccessVerdict,
    FileActionType,
    PathResolutionResult,
    PathTraversalError,
    SymlinkEscapeError,
    WorkspaceBoundaryError,
    WorkspaceBoundaryPolicy,
)

__all__ = [
    "ActualPathLinkResolver",
    "FileAccessVerdict",
    "FileActionType",
    "PathResolutionResult",
    "PathTraversalError",
    "SymlinkEscapeError",
    "WorkspaceBoundaryError",
    "WorkspaceBoundaryPolicy",
    "WorkspaceFileAccessGuard",
]
