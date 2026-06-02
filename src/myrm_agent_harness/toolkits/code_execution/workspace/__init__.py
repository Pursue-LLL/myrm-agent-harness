"""Workspace module for code execution sessions.

Manages session-scoped temporary working directories.

Core concepts:
- Workspace: logical workspace bound to a session_id
- WorkspaceService: workspace lifecycle management
- create_workspace_service: explicit ``root_dir`` factory (hosts supply configured storage root)
"""

from .models import (
    Workspace,
    WorkspaceDict,
    WorkspaceStatus,
)
from .service import WorkspaceService, create_workspace_service

__all__ = [
    "Workspace",
    "WorkspaceDict",
    "WorkspaceService",
    "WorkspaceStatus",
    "create_workspace_service",
]
