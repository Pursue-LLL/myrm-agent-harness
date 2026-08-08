"""Unit tests for _context_recovery module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools._context_recovery import (
    ensure_executor,
    restore_context_vars,
)

# ---------------------------------------------------------------------------
# restore_context_vars tests
# ---------------------------------------------------------------------------


_MOD = "myrm_agent_harness.agent.meta_tools._context_recovery"
_EXECUTORS = "myrm_agent_harness.toolkits.code_execution.executors.base"
_STORAGE = "myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind"
_CORE = "myrm_agent_harness.core.context_vars"
_APPROVAL = "myrm_agent_harness.agent.middlewares.approval"
_EVICTED = "myrm_agent_harness.agent.context_management.infra.evicted_content"
_CTX_MGMT = "myrm_agent_harness.agent.context_management.context"


class TestRestoreContextVars:
    """Tests for restore_context_vars."""

    def test_binds_executor_and_workspace(self) -> None:
        executor = MagicMock()
        context: dict[str, object] = {
            "workspace_path": "/tmp/ws",
            "workspaces_storage_root": "/tmp/storage",
            "chat_id": "chat-abc",
        }
        with (
            patch(f"{_EXECUTORS}.set_executor") as mock_set,
            patch(f"{_APPROVAL}.set_workspace_root") as mock_ws,
            patch(f"{_CORE}.workspace_root_var") as mock_ws_var,
            patch(f"{_CORE}.chat_id_var") as mock_chat_id,
            patch(f"{_STORAGE}._workspace_storage_fs_root") as mock_root,
            patch(f"{_STORAGE}.bind_workspace_storage_root"),
        ):
            mock_root.get.return_value = None
            restore_context_vars(context, executor)

        mock_set.assert_called_once_with(executor)
        mock_ws.assert_called_once_with("/tmp/ws")
        mock_ws_var.set.assert_called_once_with("/tmp/ws")
        mock_chat_id.set.assert_called_once_with("chat-abc")

    def test_skips_workspace_when_absent(self) -> None:
        executor = MagicMock()
        context: dict[str, object] = {"chat_id": "chat-xyz"}
        with (
            patch(f"{_EXECUTORS}.set_executor") as mock_set,
            patch(f"{_APPROVAL}.set_workspace_root") as mock_ws,
            patch(f"{_CORE}.workspace_root_var") as mock_ws_var,
            patch(f"{_CORE}.chat_id_var") as mock_chat_id,
            patch(f"{_STORAGE}._workspace_storage_fs_root") as mock_root,
        ):
            mock_root.get.return_value = "/already/set"
            restore_context_vars(context, executor)

        mock_set.assert_called_once_with(executor)
        mock_ws.assert_not_called()
        mock_ws_var.set.assert_not_called()
        mock_chat_id.set.assert_called_once_with("chat-xyz")

    def test_falls_back_to_session_id_for_chat_id(self) -> None:
        executor = MagicMock()
        context: dict[str, object] = {"session_id": "sess-fallback"}
        with (
            patch(f"{_EXECUTORS}.set_executor"),
            patch(
                f"{_EVICTED}.normalize_delivery_chat_id",
                return_value="normalized-chat-id",
            ) as mock_normalize,
            patch(f"{_CORE}.chat_id_var") as mock_chat_id,
            patch(f"{_STORAGE}._workspace_storage_fs_root") as mock_root,
        ):
            mock_root.get.return_value = "/set"
            restore_context_vars(context, executor)

        mock_normalize.assert_called_once_with("sess-fallback")
        mock_chat_id.set.assert_called_once_with("normalized-chat-id")


# ---------------------------------------------------------------------------
# ensure_executor tests
# ---------------------------------------------------------------------------


class TestEnsureExecutor:
    """Tests for ensure_executor."""

    def test_returns_executor_from_context_var(self) -> None:
        mock_executor = MagicMock()
        mock_config: dict[str, object] = {"configurable": {}}
        with patch(f"{_EXECUTORS}.get_executor", return_value=mock_executor):
            result = ensure_executor(mock_config)  # type: ignore[arg-type]

        assert result is mock_executor

    def test_falls_back_to_session_stash(self) -> None:
        mock_executor = MagicMock()
        mock_context = {"session_id": "sess-123", "workspace_path": "/w"}
        mock_config: dict[str, object] = {"configurable": {}}
        with (
            patch(f"{_EXECUTORS}.get_executor", return_value=None),
            patch(
                f"{_CTX_MGMT}.extract_context_from_runnable_config",
                return_value=mock_context,
            ),
            patch(f"{_EXECUTORS}.get_stashed_executor", return_value=mock_executor),
            patch(f"{_EXECUTORS}.set_executor"),
            patch(f"{_STORAGE}._workspace_storage_fs_root") as mock_root,
            patch(f"{_APPROVAL}.set_workspace_root"),
            patch(f"{_CORE}.workspace_root_var"),
            patch(f"{_CORE}.chat_id_var"),
        ):
            mock_root.get.return_value = "/set"
            result = ensure_executor(mock_config)  # type: ignore[arg-type]

        assert result is mock_executor

    def test_raises_when_no_executor_available(self) -> None:
        mock_context: dict[str, object] = {"session_id": "sess-dead"}
        mock_config: dict[str, object] = {"configurable": {}}
        with (
            patch(f"{_EXECUTORS}.get_executor", return_value=None),
            patch(
                f"{_CTX_MGMT}.extract_context_from_runnable_config",
                return_value=mock_context,
            ),
            patch(f"{_EXECUTORS}.get_stashed_executor", return_value=None),
            pytest.raises(RuntimeError, match="CodeExecutor not available"),
        ):
            ensure_executor(mock_config)  # type: ignore[arg-type]    def test_raises_when_no_session_id(self) -> None:
        mock_context: dict[str, object] = {}
        mock_config: dict[str, object] = {"configurable": {}}
        with (
            patch(f"{_EXECUTORS}.get_executor", return_value=None),
            patch(
                f"{_CTX_MGMT}.extract_context_from_runnable_config",
                return_value=mock_context,
            ),pytest.raises(RuntimeError, match="CodeExecutor not available")
        ):
            ensure_executor(mock_config)  # type: ignore[arg-type]
