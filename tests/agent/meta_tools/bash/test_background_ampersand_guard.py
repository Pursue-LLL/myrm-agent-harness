"""Trailing ``&`` orphan-guard tests for background spawn.

`spawn_background` runs ``sh -c <command>``. A bare trailing ``&`` makes ``sh``
return immediately while the real process keeps running detached, so the
registered PID points at an exited shell and bash_process_tool cannot manage it.
These tests lock the normalization and the prompt contract.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash._executor.background_mixin import (
    strip_trailing_background_ampersand,
)
from myrm_agent_harness.agent.meta_tools.bash._executor.executor import BashExecutor
from myrm_agent_harness.agent.meta_tools.bash._tool.tool_description import TOOL_DESCRIPTION


def _mock_executor() -> MagicMock:
    executor = MagicMock()
    executor.config = MagicMock()
    executor.config.network.allow_network = True
    executor.config.network.get_effective_allowed_hosts.return_value = []
    executor.config.local.max_execution_time = 120
    executor.config.mcp_proxy.socket_path = "/tmp/mcp.sock"
    executor.get_executor_name.return_value = "mock"
    executor.get_mcp_communication_config.return_value = None
    return executor


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("python server.py &", "python server.py"),
        ("python server.py&", "python server.py"),
        ("  python server.py &  ", "  python server.py"),
        ("uvicorn app:app --port 8000 &", "uvicorn app:app --port 8000"),
        ("python server.py 2>&1 &", "python server.py 2>&1"),
        ("cmd1 && cmd2 &", "cmd1 && cmd2"),
        ("python server.py &\n", "python server.py"),
        ("python server.py &\r\n", "python server.py"),
        ("cmd\n&", "cmd"),
        ("cmd\n&  ", "cmd"),
        ("cmd && &", "cmd &&"),
    ],
)
def test_strip_bare_trailing_ampersand(command: str, expected: str) -> None:
    assert strip_trailing_background_ampersand(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        "echo hi",
        "make build && pytest",
        "python server.py 2>&1",
        "",
        "cmd & # keep this comment",
        "cmd1 && cmd2 &&",
        "cmd1 & cmd2",
        'echo "a & b"',
        "echo 'a & b'",
        "cmd & &&",
    ],
)
def test_preserve_non_orphaning_commands(command: str) -> None:
    """``&&`` chains, mid-command ``&``, quotes, and plain commands are untouched."""
    assert strip_trailing_background_ampersand(command) == command


def test_background_section_warns_against_trailing_ampersand() -> None:
    """Prompt must tell the model not to append ``&`` when backgrounding."""
    assert "run_in_background=true" in TOOL_DESCRIPTION
    assert "不要" in TOOL_DESCRIPTION
    assert "`&`" in TOOL_DESCRIPTION
    assert "自动后台化" in TOOL_DESCRIPTION
    assert "pid 失效" in TOOL_DESCRIPTION


@pytest.mark.asyncio
async def test_spawn_background_strips_trailing_ampersand() -> None:
    """The spawn entry point strips the trailing ``&`` before handoff."""
    executor = _mock_executor()
    proc = MagicMock()
    executor.spawn_background_process = AsyncMock(return_value=proc)
    executor.bind_workspace = MagicMock()

    bash_exec = BashExecutor(executor, enable_skill_execution=False)
    fake_info = MagicMock(pid=4242, command="python server.py", status="running")

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._background.registry.get_background_registry",
        ) as mock_registry,
    ):
        mock_registry.return_value.register = AsyncMock(return_value=fake_info)
        info = await bash_exec.spawn_background("python server.py &", session_id="sess-1")

    assert info.pid == 4242
    assert executor.spawn_background_process.await_args is not None
    spawned_command = executor.spawn_background_process.await_args.args[0].args[1]
    assert spawned_command == "python server.py"
    mock_registry.return_value.register.assert_awaited_once()


@pytest.mark.asyncio
async def test_spawn_background_clears_skill_cache_on_workspace_invalidation() -> None:
    """Invalidated workspace id triggers skill cache clear before spawn."""
    executor = _mock_executor()
    proc = MagicMock()
    executor.spawn_background_process = AsyncMock(return_value=proc)
    executor.bind_workspace = MagicMock()

    bash_exec = BashExecutor(executor, enable_skill_execution=False)
    bash_exec._skill_manager.clear_workspace_cache = MagicMock()
    fake_info = MagicMock(pid=5151, command="sleep 1", status="running")

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), "stale-ws-id")),
        ),
        patch.object(bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._background.registry.get_background_registry",
        ) as mock_registry,
    ):
        mock_registry.return_value.register = AsyncMock(return_value=fake_info)
        await bash_exec.spawn_background("sleep 1", session_id="sess-2")

    bash_exec._skill_manager.clear_workspace_cache.assert_called_once_with("stale-ws-id")


@pytest.mark.asyncio
async def test_spawn_background_raises_when_executor_lacks_spawn() -> None:
    """Executors without spawn_background_process surface BACKGROUND_UNSUPPORTED."""
    from myrm_agent_harness.agent.meta_tools.bash._executor.error import BashExecutionError

    executor = _mock_executor()
    del executor.spawn_background_process

    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"),
        pytest.raises(BashExecutionError) as exc_info,
    ):
        await bash_exec.spawn_background("sleep 1", session_id="sess-3")

    assert exc_info.value.error_category == "BACKGROUND_UNSUPPORTED"


@pytest.mark.asyncio
async def test_spawn_background_raises_on_quota_exceeded() -> None:
    """BackgroundQuotaError kills the spawned proc and raises BashExecutionError."""
    from myrm_agent_harness.agent.meta_tools.bash._background.registry import BackgroundQuotaError
    from myrm_agent_harness.agent.meta_tools.bash._executor.error import BashExecutionError

    executor = _mock_executor()
    proc = MagicMock()
    proc.kill = MagicMock()
    executor.spawn_background_process = AsyncMock(return_value=proc)
    executor.bind_workspace = MagicMock()

    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._background.registry.get_background_registry",
        ) as mock_registry,
        pytest.raises(BashExecutionError) as exc_info,
    ):
        mock_registry.return_value.register = AsyncMock(
            side_effect=BackgroundQuotaError("sess-4", 5),
        )
        await bash_exec.spawn_background("sleep 1", session_id="sess-4")

    assert exc_info.value.error_category == "BACKGROUND_QUOTA_EXCEEDED"
    proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_spawn_background_strips_after_fence_unwrap() -> None:
    """A markdown-fenced command with trailing ``&`` is unwrapped then stripped."""
    executor = _mock_executor()
    proc = MagicMock()
    executor.spawn_background_process = AsyncMock(return_value=proc)
    executor.bind_workspace = MagicMock()

    bash_exec = BashExecutor(executor, enable_skill_execution=False)
    fake_info = MagicMock(pid=4343, command="python server.py", status="running")

    fenced = "```bash\npython server.py &\n```"
    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._background.registry.get_background_registry",
        ) as mock_registry,
    ):
        mock_registry.return_value.register = AsyncMock(return_value=fake_info)
        info = await bash_exec.spawn_background(fenced, session_id="sess-1")

    assert info.pid == 4343
    assert executor.spawn_background_process.await_args is not None
    spawned_command = executor.spawn_background_process.await_args.args[0].args[1]
    assert spawned_command == "python server.py"
    mock_registry.return_value.register.assert_awaited_once()
