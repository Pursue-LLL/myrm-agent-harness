"""Workspace Manager

Thin delegation layer over WorkspaceService for code execution sessions.
BashExecutor is instantiated per tool call (to avoid LangGraph checkpointer
serialization issues), so per-instance caching is ineffective. Workspace
lifecycle management is delegated entirely to WorkspaceService.

[INPUT]
- toolkits.code_execution::Workspace (POS: Code execution toolkit entry point. Aggregates execution configuration, executor implementations, workspace management, and factory functions for the Agent-in-Sandbox architecture.)
- toolkits.code_execution.workspace::WorkspaceService (POS: Workspace data models for code execution sessions.)

[OUTPUT]
- WorkspaceManager: Workspace manager — delegates to WorkspaceService.

[POS]
Workspace Manager
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution import Workspace
    from myrm_agent_harness.toolkits.code_execution.workspace import WorkspaceService

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Workspace manager — delegates to WorkspaceService.

    Responsibilities:
    - Get or create user workspaces via WorkspaceService
    - Provide workspace path resolution
    - Trigger workspace timestamp updates
    """

    def __init__(self, workspace_service: "WorkspaceService | None" = None) -> None:
        self._workspace_service = workspace_service

    def _get_service(self) -> "WorkspaceService":
        if self._workspace_service is None:
            from myrm_agent_harness.toolkits.code_execution import create_workspace_service
            from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
                workspace_storage_fs_root_strict,
            )

            self._workspace_service = create_workspace_service(
                root_dir=workspace_storage_fs_root_strict(),
            )
        return self._workspace_service

    async def get_or_create(self, session_id: str | None) -> tuple["Workspace | None", str | None]:
        """Get or create a workspace for the given session.

        Args:
            session_id: Session identifier (framework concept).

        Returns:
            (workspace, invalidated_workspace_id) tuple.
            invalidated_workspace_id is always None (kept for API compatibility).
        """
        if not session_id:
            return None, None

        workspace = await self._get_service().get_or_create(session_id=session_id)
        return workspace, None

    def get_workspace_path(self, workspace: "Workspace | None") -> str | None:
        """Get the absolute filesystem path of a workspace."""
        if not workspace:
            return None
        return self._get_service().get_workspace_absolute_path(workspace)

    async def update_workspace_timestamp(self, workspace: "Workspace | None") -> None:
        """Update the last_used_at timestamp of a workspace."""
        if workspace:
            await self._get_service().update(workspace)
