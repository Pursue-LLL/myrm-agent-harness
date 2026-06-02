"""WorkspaceManager tests — delegation layer over WorkspaceService."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash.workspace_manager import WorkspaceManager


class TestWorkspaceManager:
    def test_init_with_service(self):
        mock_service = MagicMock()
        mgr = WorkspaceManager(workspace_service=mock_service)
        assert mgr._workspace_service is mock_service

    def test_init_without_service(self):
        mgr = WorkspaceManager()
        assert mgr._workspace_service is None

    @pytest.mark.asyncio
    async def test_get_or_create_no_session(self):
        mgr = WorkspaceManager()
        workspace, invalidated = await mgr.get_or_create(None)
        assert workspace is None
        assert invalidated is None

    @pytest.mark.asyncio
    async def test_get_or_create_empty_session(self):
        mgr = WorkspaceManager()
        workspace, invalidated = await mgr.get_or_create("")
        assert workspace is None
        assert invalidated is None

    @pytest.mark.asyncio
    async def test_get_or_create_delegates_to_service(self):
        mock_workspace = MagicMock()
        mock_service = MagicMock()
        mock_service.get_or_create = AsyncMock(return_value=mock_workspace)

        mgr = WorkspaceManager(workspace_service=mock_service)
        workspace, invalidated = await mgr.get_or_create("session-123")

        assert workspace is mock_workspace
        assert invalidated is None
        mock_service.get_or_create.assert_awaited_once_with(session_id="session-123")

    def test_get_workspace_path_none_workspace(self):
        mgr = WorkspaceManager()
        assert mgr.get_workspace_path(None) is None

    def test_get_workspace_path_delegates(self):
        mock_service = MagicMock()
        mock_service.get_workspace_absolute_path.return_value = "/tmp/workspace/abc"
        mock_workspace = MagicMock()

        mgr = WorkspaceManager(workspace_service=mock_service)
        path = mgr.get_workspace_path(mock_workspace)

        assert path == "/tmp/workspace/abc"
        mock_service.get_workspace_absolute_path.assert_called_once_with(mock_workspace)

    @pytest.mark.asyncio
    async def test_update_timestamp_none_workspace(self):
        mock_service = MagicMock()
        mock_service.update = AsyncMock()
        mgr = WorkspaceManager(workspace_service=mock_service)

        await mgr.update_workspace_timestamp(None)
        mock_service.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_timestamp_delegates(self):
        mock_service = MagicMock()
        mock_service.update = AsyncMock()
        mock_workspace = MagicMock()

        mgr = WorkspaceManager(workspace_service=mock_service)
        await mgr.update_workspace_timestamp(mock_workspace)

        mock_service.update.assert_awaited_once_with(mock_workspace)

    @pytest.mark.asyncio
    async def test_lazy_service_creation(self):
        mgr = WorkspaceManager()

        mock_service = MagicMock()
        mock_service.get_or_create = AsyncMock(return_value=MagicMock())
        agg = Path("/srv/ws-aggregate")

        with (
            patch(
                "myrm_agent_harness.toolkits.code_execution.create_workspace_service",
                return_value=mock_service,
            ) as mock_create,
            patch(
                "myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind.workspace_storage_fs_root_strict",
                return_value=agg,
            ),
        ):
            await mgr.get_or_create("session-456")
            mock_create.assert_called_once_with(root_dir=agg)
            assert mgr._workspace_service is mock_service
