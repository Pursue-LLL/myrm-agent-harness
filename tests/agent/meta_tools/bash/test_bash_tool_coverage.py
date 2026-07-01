"""Unit coverage for bash_tool split modules (mock-based)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash.bash_tool import create_bash_tool
from myrm_agent_harness.agent.meta_tools.bash.bash_tool_background_listeners import (
    build_background_listeners,
    classify_background_exit,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_tool_helpers import (
    get_os_hint,
    restore_context_vars,
    track_context_access_in_command,
)


class _FakeBackgroundInfo:
    def __init__(
        self,
        *,
        pid: int = 1,
        command: str = "sleep 1",
        status: str = "exited",
        exit_code: int | None = 0,
    ) -> None:
        self.pid = pid
        self.command = command
        self.status = status
        self.exit_code = exit_code


@pytest.mark.asyncio
async def test_build_background_listeners_dispatch_progress_and_finish() -> None:
    config: dict[str, object] = {}
    info = _FakeBackgroundInfo(pid=9, status="exited", exit_code=137)

    with patch(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
        AsyncMock(),
    ) as mock_dispatch:
        finish, progress = build_background_listeners(session_id="sess", config=config)  # type: ignore[arg-type]
        await progress(info, {"message": "50%", "progress": 50})
        await finish(info)

    assert mock_dispatch.await_count == 2


def test_classify_background_exit_oom() -> None:
    info = _FakeBackgroundInfo(status="exited", exit_code=137)
    assert classify_background_exit(info) == "oom_killed"


def test_get_os_hint_contains_os_label() -> None:
    hint = get_os_hint()
    assert "当前系统" in hint or "OS:" in hint


@pytest.mark.asyncio
async def test_track_context_access_records_persistent_paths() -> None:
    tracker = MagicMock()
    tracker.record_access = AsyncMock()
    with patch(
        "myrm_agent_harness.runtime.context.file_access_tracker.get_file_access_tracker",
        AsyncMock(return_value=tracker),
    ):
        await track_context_access_in_command(
            "cat /persistent/foo/.context/bar.txt",
            session_id="sess-1",
        )
    tracker.record_access.assert_awaited()


def test_restore_context_vars_binds_executor_and_workspace() -> None:
    executor = MagicMock()
    context = {
        "workspace_path": "/tmp/ws",
        "workspaces_storage_root": "/tmp/storage",
    }
    with (
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.set_executor",
        ) as mock_set,
        patch(
            "myrm_agent_harness.agent.middlewares.approval.set_workspace_root",
        ) as mock_ws,
        patch(
            "myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind._workspace_storage_fs_root",
        ) as mock_root,
        patch(
            "myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind.bind_workspace_storage_root",
        ) as mock_bind,
    ):
        mock_root.get.return_value = None
        restore_context_vars(context, executor)

    mock_set.assert_called_once_with(executor)
    mock_ws.assert_called_once_with("/tmp/ws")
    mock_bind.assert_called_once()


def _patch_bash_tool_success(mock_execute_result: dict[str, object]):
    mock_executor = MagicMock()
    mock_executor.get_executor_name.return_value = "test"
    mock_bash_executor = AsyncMock()
    mock_bash_executor.execute.return_value = mock_execute_result
    mock_bash_executor.consume_python_c_transform_hint.return_value = None

    return (
        mock_bash_executor,
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_tool.extract_context_from_runnable_config",
            return_value={"session_id": "test-session", "supports_vision": False},
        ),
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_executor.BashExecutor",
            return_value=mock_bash_executor,
        ),
        patch(
            "myrm_agent_harness.agent.skills.mcp.notify_registry.session_scope",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=False),
            ),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_tool.track_context_access_in_command",
            AsyncMock(),
        ),
    )


@pytest.mark.asyncio
async def test_bash_tool_background_path_returns_pid_metadata() -> None:
    mock_executor = MagicMock()
    mock_bash_executor = AsyncMock()
    fake_info = MagicMock(pid=99, command="sleep 1", status="running")
    mock_bash_executor.spawn_background.return_value = fake_info

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_tool.extract_context_from_runnable_config",
            return_value={"session_id": "test-session"},
        ),
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_executor.BashExecutor",
            return_value=mock_bash_executor,
        ),
        patch(
            "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
            AsyncMock(),
        ),
    ):
        tool = create_bash_tool()
        result = await tool.ainvoke(
            {"command": "sleep 60", "reason": "bg", "run_in_background": True},
            config={"configurable": {"context": {"session_id": "s"}}},
        )

    assert result["metadata"]["background"] is True
    assert result["metadata"]["pid"] == 99


@pytest.mark.asyncio
async def test_bash_tool_foreground_success_returns_content() -> None:
    mocks = _patch_bash_tool_success(
        {
            "stdout": "ok",
            "stderr": "",
            "exit_code": "0",
            "mcp_metadata": {},
            "generated_files": [],
        }
    )
    mock_be, *patches = mocks

    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        tool = create_bash_tool()
        result = await tool.ainvoke(
            {"command": "echo ok", "reason": "test"},
            config={"configurable": {"context": {"session_id": "s"}}},
        )

    assert isinstance(result, dict)
    assert "content" in result
    mock_be.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_bash_tool_foreground_with_truncation_eviction_and_hint() -> None:
    mock_executor = MagicMock()
    mock_bash_executor = AsyncMock()
    mock_bash_executor.execute.return_value = {
        "stdout": "x" * 5000,
        "stderr": "",
        "exit_code": "0",
        "mcp_metadata": {"tool": "mcp"},
        "generated_files": [],
        "evicted_ref": "vault://big",
    }
    mock_bash_executor.consume_python_c_transform_hint.return_value = "rewrite hint"

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_tool.extract_context_from_runnable_config",
            return_value={"session_id": "test-session", "supports_vision": False},
        ),
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_executor.BashExecutor",
            return_value=mock_bash_executor,
        ),
        patch(
            "myrm_agent_harness.agent.skills.mcp.notify_registry.session_scope",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=False),
            ),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_tool.track_context_access_in_command",
            AsyncMock(),
        ),
        patch(
            "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
            AsyncMock(),
        ) as mock_dispatch,
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_tool.format_result",
            return_value=("truncated", True, {"truncated": True}),
        ),
    ):
        tool = create_bash_tool(
            skills=[SimpleNamespace(name="s", oauth_issuer="iss", storage_path="/skills/s")],
            skill_env_map={"s": {}},
            global_env={"G": "1"},
        )
        result = await tool.ainvoke(
            {"command": "cat /persistent/x/.context/y.txt", "reason": "test"},
            config={"configurable": {"context": {"session_id": "s"}}},
        )

    assert result["metadata"] == {"tool": "mcp"}
    assert mock_dispatch.await_count >= 3


@pytest.mark.asyncio
async def test_bash_tool_interactive_command_raises_tool_error() -> None:
    with patch(
        "myrm_agent_harness.agent.meta_tools.bash.bash_tool.check_interactive_command",
        return_value="interactive not allowed",
    ):
        tool = create_bash_tool()
        with pytest.raises(Exception, match="interactive not allowed"):
            await tool.ainvoke(
                {"command": "vim file", "reason": "test"},
                config={"configurable": {"context": {"session_id": "s"}}},
            )


@pytest.mark.asyncio
async def test_bash_tool_restores_stashed_executor() -> None:
    mock_executor = MagicMock()
    mock_bash_executor = AsyncMock()
    mock_bash_executor.execute.return_value = {
        "stdout": "ok",
        "stderr": "",
        "exit_code": "0",
        "mcp_metadata": {},
        "generated_files": [],
    }
    mock_bash_executor.consume_python_c_transform_hint.return_value = None

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_tool.extract_context_from_runnable_config",
            return_value={"session_id": "sess-1", "workspace_path": "/ws"},
        ),
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.get_stashed_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_tool.restore_context_vars",
        ) as mock_restore,
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_executor.BashExecutor",
            return_value=mock_bash_executor,
        ),
        patch(
            "myrm_agent_harness.agent.skills.mcp.notify_registry.session_scope",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=False),
            ),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_tool.track_context_access_in_command",
            AsyncMock(),
        ),
    ):
        tool = create_bash_tool()
        await tool.ainvoke(
            {"command": "echo ok", "reason": "test"},
            config={"configurable": {"context": {"session_id": "sess-1"}}},
        )

    mock_restore.assert_called_once()


@pytest.mark.asyncio
async def test_bash_tool_background_requires_session_id() -> None:
    mock_executor = MagicMock()
    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_tool.extract_context_from_runnable_config",
            return_value={"session_id": ""},
        ),
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_executor.BashExecutor",
            return_value=AsyncMock(),
        ),
    ):
        tool = create_bash_tool()
        with pytest.raises(Exception, match="run_in_background requires"):
            await tool.ainvoke(
                {"command": "sleep 1", "reason": "bg", "run_in_background": True},
                config={"configurable": {"context": {}}},
            )


@pytest.mark.asyncio
async def test_maybe_build_image_blocks_exception_str_fallback_and_overflow() -> None:
    from langchain_core.messages.content import create_text_block

    from myrm_agent_harness.agent.meta_tools.bash.bash_tool_multimodal import (
        MAX_IMAGES_PER_RETURN,
        maybe_build_image_blocks,
    )

    image_paths = [f"/tmp/img{i}.png" for i in range(MAX_IMAGES_PER_RETURN + 2)]
    image_block = create_text_block("inline-image")

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.image_reader.is_image_path",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.require_executor",
            return_value=MagicMock(),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.image_reader.read_image_as_content_blocks",
            AsyncMock(
                side_effect=[OSError("fail"), "text-fallback"]
                + [[image_block]] * MAX_IMAGES_PER_RETURN
            ),
        ),
    ):
        blocks = await maybe_build_image_blocks(
            text_content="chart",
            generated_files=image_paths,
            context={"supports_vision": True},
        )

    assert blocks is not None
    # 1 text_content + 1 str-fallback + 2 image blocks + 1 overflow notice = 5
    assert len(blocks) == 5
