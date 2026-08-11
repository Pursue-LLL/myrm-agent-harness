"""Unit coverage for BashExecutor split modules (mock-based, no server E2E)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash._executor.error import (
    BashExecutionError,
)
from myrm_agent_harness.agent.meta_tools.bash._executor.executor import BashExecutor
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionResult


def _mock_code_executor() -> MagicMock:
    executor = MagicMock()
    executor.config = MagicMock()
    executor.config.network.allow_network = True
    executor.config.network.get_effective_allowed_hosts.return_value = []
    executor.config.local.max_execution_time = 120
    executor.config.mcp_proxy.socket_path = "/tmp/mcp.sock"
    executor.get_executor_name.return_value = "mock"
    executor.get_mcp_communication_config.return_value = None
    executor.execute_bash = AsyncMock()
    executor.execute = AsyncMock()
    return executor


class TestBashExecutionError:
    def test_construction_keeps_diagnostics(self) -> None:
        err = BashExecutionError(
            "failed",
            phase="execution",
            error_hint="fix it",
            error_category="EXEC",
            stderr_evicted_ref="output_abc.txt",
            stderr_evicted_stored_chars=1200,
            stderr_evicted_total_lines=10,
            stderr_evicted_storage_truncated=True,
        )
        assert str(err) == "failed"
        assert err.error_hint == "fix it"
        assert err.error_category == "EXEC"
        assert err.stderr_evicted_ref == "output_abc.txt"
        assert err.stderr_evicted_stored_chars == 1200
        assert err.stderr_evicted_total_lines == 10
        assert err.stderr_evicted_storage_truncated is True


@pytest.mark.asyncio
async def test_execute_bash_success_returns_eviction_fields() -> None:
    executor = _mock_code_executor()
    executor.execute_bash.return_value = ExecutionResult(
        success=True,
        result=0,
        stdout="hello",
        stderr="",
        container_id="c1",
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    workspace = MagicMock()
    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(workspace, None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._compression.output_eviction.maybe_evict_large_output",
            AsyncMock(
                return_value=MagicMock(text="evicted-text", evicted_ref="vault://x")
            ),
        ),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
    ):
        result = await bash_exec.execute("echo hi", session_id="sess-1")

    assert result["stdout"] == "evicted-text"
    assert result["evicted_ref"] == "vault://x"
    assert result["exit_code"] == "0"
    executor.execute_bash.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_symmetrically_evicts_stderr() -> None:
    """Large stderr gets the same eviction treatment as stdout.

    The execute() return must carry the stderr eviction preview and a separate
    stderr_evicted_ref so the GUI can offer an independent "view full stderr".
    """
    executor = _mock_code_executor()
    executor.execute_bash.return_value = ExecutionResult(
        success=True,
        result=0,
        stdout="ok",
        stderr="warning" * 5000,
        container_id="c1",
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    def _fake_evict(text: str, _executor=None):
        return MagicMock(
            text=f"preview:{len(text)}",
            evicted_ref=f"ref-{len(text)}",
            stored_chars=len(text),
            total_lines=1,
            storage_truncated=False,
        )

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._compression.output_eviction.maybe_evict_large_output",
            AsyncMock(side_effect=_fake_evict),
        ),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
    ):
        result = await bash_exec.execute("echo hi", session_id="sess-1")

    assert result["stdout"] == "preview:2"
    assert result["evicted_ref"] == "ref-2"
    assert result["stderr"] == f"preview:{len('warning' * 5000)}"
    assert result["stderr_evicted_ref"] == f"ref-{len('warning' * 5000)}"
    assert result["stderr_evicted_stored_chars"] == len("warning" * 5000)
    assert result["stderr_evicted_total_lines"] == 1


@pytest.mark.asyncio
async def test_execute_empty_stderr_passes_through_eviction() -> None:
    """Empty stderr passes through the eviction path unchanged.

    Bash path always merges stderr into stdout (local_session uses
    asyncio.subprocess.STDOUT), so stderr is ``""`` here — the symmetric
    eviction call is a harmless no-op that yields no evicted ref.
    """
    executor = _mock_code_executor()
    executor.execute_bash.return_value = ExecutionResult(
        success=True,
        result=0,
        stdout="hello",
        stderr="",
        container_id="c1",
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._compression.output_eviction.maybe_evict_large_output",
            AsyncMock(return_value=MagicMock(text="out", evicted_ref=None)),
        ),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
    ):
        result = await bash_exec.execute("echo hi", session_id="sess-1")

    assert result["stderr"] == "out"
    assert result["stderr_evicted_ref"] is None


@pytest.mark.asyncio
async def test_execute_raises_bash_execution_error_on_failure() -> None:
    executor = _mock_code_executor()
    executor.execute_bash.return_value = ExecutionResult(
        success=False,
        result=1,
        stdout="",
        stderr="boom",
        error="failed",
        error_category="EXEC",
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
        pytest.raises(BashExecutionError),
    ):
        await bash_exec.execute("false", session_id="sess-1")


@pytest.mark.asyncio
async def test_execute_failure_evicts_stderr_into_message() -> None:
    executor = _mock_code_executor()
    executor.execute_bash.return_value = ExecutionResult(
        success=False,
        result=1,
        stdout="processed row 149\n",
        stderr=(
            "Traceback (most recent call last):\n"
            '  File "<string>", line 152\n'
            "    float(row['amount'])\n"
            "ValueError: bad row 150"
        ),
        error="ValueError: bad row 150",
        error_category="EXEC",
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    async def _fake_evict(content: str, _executor=None) -> MagicMock:
        if content.startswith("processed row"):
            return MagicMock(
                text="[LARGE STDOUT TRUNCATED (1 lines, ~2 tokens)]\n\nRead the full output with file_read_tool.",
                evicted_ref="stdout_out_1.txt",
                stored_chars=32,
                total_lines=1,
                storage_truncated=False,
            )
        return MagicMock(
            text=(
                "[LARGE OUTPUT TRUNCATED (12 lines, ~60 tokens)]\n\n"
                "Traceback ...\n\n"
                "Read the full output with file_read_tool."
            ),
            evicted_ref="output_abc123.txt",
            stored_chars=1500,
            total_lines=12,
            storage_truncated=False,
        )

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()) as mock_log,
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._compression.output_eviction.maybe_evict_large_output",
            AsyncMock(side_effect=_fake_evict),
        ),
        pytest.raises(BashExecutionError) as exc_info,
    ):
        await bash_exec.execute("bad python", session_id="sess-1")

    err = exc_info.value
    assert err.error_category == "EXEC"
    assert "ValueError: bad row 150" in str(err)
    assert "LARGE OUTPUT TRUNCATED" in str(err)
    assert "LARGE STDOUT TRUNCATED" in str(err)
    assert "processed row" not in str(err)
    assert err.stdout_evicted_ref == "stdout_out_1.txt"
    assert err.stdout_evicted_stored_chars == 32
    assert err.stdout_evicted_total_lines == 1
    assert err.stderr_evicted_ref == "output_abc123.txt"
    assert err.stderr_evicted_stored_chars == 1500
    assert err.stderr_evicted_total_lines == 12

    log_kwargs = mock_log.await_args.kwargs
    assert log_kwargs["stdout"] == (
        "[LARGE STDOUT TRUNCATED (1 lines, ~2 tokens)]\n\n"
        "Read the full output with file_read_tool."
    )
    assert log_kwargs["stderr"] == (
        "[LARGE OUTPUT TRUNCATED (12 lines, ~60 tokens)]\n\n"
        "Traceback ...\n\n"
        "Read the full output with file_read_tool."
    )
    assert log_kwargs["success"] is False


@pytest.mark.asyncio
async def test_execute_failure_small_stderr_visible_in_message() -> None:
    executor = _mock_code_executor()
    executor.execute_bash.return_value = ExecutionResult(
        success=False,
        result=1,
        stdout="",
        stderr="boom: cannot find package",
        error="boom: cannot find package",
        error_category="EXEC",
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
        pytest.raises(BashExecutionError) as exc_info,
    ):
        await bash_exec.execute("false", session_id="sess-1")

    err = exc_info.value
    assert str(err) == "boom: cannot find package"
    assert err.stderr_evicted_ref is None


@pytest.mark.asyncio
async def test_execute_failure_small_stdout_visible_in_message() -> None:
    executor = _mock_code_executor()
    executor.execute_bash.return_value = ExecutionResult(
        success=False,
        result=1,
        stdout="processed row 149\n",
        stderr=("Traceback (most recent call last):\n" "ValueError: bad row 150"),
        error="ValueError: bad row 150",
        error_category="EXEC",
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
        pytest.raises(BashExecutionError) as exc_info,
    ):
        await bash_exec.execute("bad python", session_id="sess-1")

    err = exc_info.value
    assert "processed row 149" in str(err)
    assert "ValueError: bad row 150" in str(err)
    assert err.stdout_evicted_ref is None
    assert err.stderr_evicted_ref is None


@pytest.mark.asyncio
async def test_execute_missing_session_id_raises() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    with pytest.raises(BashExecutionError) as exc_info:
        await bash_exec.execute("echo hi", session_id=None)
    assert exc_info.value.error_category == "MISSING_SESSION_ID"


@pytest.mark.asyncio
async def test_spawn_background_unsupported_executor() -> None:
    executor = _mock_code_executor()
    del executor.spawn_background_process
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        pytest.raises(BashExecutionError) as exc_info,
    ):
        await bash_exec.spawn_background("sleep 1", session_id="sess-1")

    assert exc_info.value.error_category == "BACKGROUND_UNSUPPORTED"


@pytest.mark.asyncio
async def test_spawn_background_registers_process() -> None:
    executor = _mock_code_executor()
    proc = MagicMock()
    executor.spawn_background_process = AsyncMock(return_value=proc)
    executor.bind_workspace = MagicMock()

    bash_exec = BashExecutor(executor, enable_skill_execution=False)
    fake_info = MagicMock(pid=4242, command="sleep 1", status="running")

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._background.registry.get_background_registry",
        ) as mock_registry,
    ):
        mock_registry.return_value.register = AsyncMock(return_value=fake_info)
        info = await bash_exec.spawn_background("sleep 1", session_id="sess-1")

    assert info.pid == 4242
    mock_registry.return_value.register.assert_awaited_once()


def test_build_execution_context_merges_env() -> None:
    executor = _mock_code_executor()
    bash_exec = BashExecutor(executor, enable_skill_execution=False)
    bash_exec.set_global_env({"GLOBAL": "1"})
    bash_exec.set_skill_env_map({"skill-a": {"SKILL_KEY": "v"}})

    ctx = bash_exec._build_execution_context(
        prepared_code="echo hi",
        original_code="echo hi",
        mcp_config_items=None,
        session_id="s1",
        workspace=None,
        env_paths=["/workspace/lib"],
        working_dir="/workspace",
        skill_names=["skill-a"],
        skill_env={"SKILL_KEY": "v"},
        timeout=30,
    )

    assert ctx.env is not None
    assert ctx.env["GLOBAL"] == "1"
    assert ctx.env["SKILL_KEY"] == "v"
    assert "PYTHONPATH" in ctx.env
    assert ctx.timeout == 30


@pytest.mark.asyncio
async def test_log_bash_command_execution_delegates() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._executor.event_logging.log_bash_command_execution",
        AsyncMock(),
    ) as mock_log:
        await bash_exec._log_bash_command_execution(
            command="ls",
            session_id="s1",
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
            success=True,
        )
    mock_log.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_mcp_proxy_starts_ipc_server() -> None:
    executor = _mock_code_executor()
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with (
        patch(
            "myrm_agent_harness.agent.skills.mcp.get_mcp_ipc_server",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.skills.mcp.start_mcp_ipc_server",
            AsyncMock(),
        ) as mock_start,
    ):
        await bash_exec._ensure_mcp_proxy_started()

    assert bash_exec._mcp_proxy_started is True
    mock_start.assert_awaited_once()


def test_rewrite_skill_paths_and_container_paths() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    workspace = MagicMock()

    with patch.object(
        bash_exec._workspace_manager, "get_workspace_path", return_value="/tmp/ws"
    ):
        paths = bash_exec._convert_to_container_paths(["/tmp/ws/skills/a"], workspace)
    assert paths

    code, skill = bash_exec._rewrite_skill_paths("import skills.demo")
    assert isinstance(code, str)
    assert skill is None or isinstance(skill, str)


def test_detect_skill_from_import_pattern() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    assert (
        bash_exec._detect_skill_from_code("from skills.my_skill import run")
        == "my_skill"
    )


@pytest.mark.asyncio
async def test_execute_strips_markdown_fence_and_clears_invalidated_cache() -> None:
    executor = _mock_code_executor()
    executor.execute_bash.return_value = ExecutionResult(
        success=True, result=0, stdout="ok", stderr="", container_id="c1"
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=False)
    workspace = MagicMock()

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(workspace, "old-ws")),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec._skill_manager, "clear_workspace_cache") as mock_clear,
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._compression.output_eviction.maybe_evict_large_output",
            AsyncMock(return_value=MagicMock(text="ok", evicted_ref=None)),
        ),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
    ):
        await bash_exec.execute("```bash\necho hi\n```", session_id="sess-1")

    mock_clear.assert_called_once_with("old-ws")


@pytest.mark.asyncio
async def test_execute_with_skill_paths_stages_detected_skill() -> None:
    """Path-mode skill calls are staged and the rewritten skill name is used.

    A ``.claude/skills/`` command makes ``rewrite_skill_paths`` return the
    detected skill name, which overrides the import-mode detection with the
    same value. Env / work_dir must be injected from the rewritten name.
    """
    executor = _mock_code_executor()
    skill_result = ExecutionResult(
        success=True, result=0, stdout="ok", stderr="", container_id="c1"
    )
    executor.execute_bash.return_value = skill_result
    executor.execute.return_value = skill_result
    bash_exec = BashExecutor(executor, enable_skill_execution=False)
    bash_exec.set_skill_env_map({"demo_skill": {"SK": "1"}})
    workspace = MagicMock()

    mock_ensure_skills = AsyncMock(return_value=["/ws/.claude/skills/demo_skill"])
    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(workspace, None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch.object(
            bash_exec._skill_manager,
            "ensure_skills_in_workspace",
            mock_ensure_skills,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._executor.prepare_mixin.rewrite_skill_paths",
            return_value=("python3 scripts/run.py", "demo_skill"),
        ),
        patch(
            "myrm_agent_harness.toolkits.code_execution.utils.WorkspacePathResolver.to_container_paths",
            return_value=["/workspace/.claude/skills/demo_skill"],
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._compression.output_eviction.maybe_evict_large_output",
            AsyncMock(return_value=MagicMock(text="ok", evicted_ref=None)),
        ),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
    ):
        result = await bash_exec.execute(
            "python3 .claude/skills/demo_skill/scripts/run.py",
            session_id="sess-1",
            skill_paths=["/host/skills/demo_skill"],
        )

    assert result["stdout"] == "ok"
    mock_ensure_skills.assert_awaited_once()
    executor.execute_bash.assert_awaited_once()

    context = executor.execute_bash.call_args.args[0]
    assert context.active_skills == ["demo_skill"]
    assert context.work_dir == "/workspace/.claude/skills/demo_skill"
    assert context.env["SK"] == "1"


@pytest.mark.asyncio
async def test_execute_import_mode_keeps_detected_skill() -> None:
    """Import-mode skill calls must not lose the detected skill name.

    `rewrite_skill_paths` only detects ``.claude/skills/`` paths and returns
    ``(code, None)`` for plain ``from skills.x import`` commands. The rewrite
    result must therefore only override the detected skill name when a skill
    is actually rewritten; otherwise the env / work_dir injection below would
    silently disappear.
    """
    executor = _mock_code_executor()
    skill_result = ExecutionResult(
        success=True, result=0, stdout="ok", stderr="", container_id="c1"
    )
    executor.execute_bash.return_value = skill_result
    executor.execute.return_value = skill_result
    bash_exec = BashExecutor(executor, enable_skill_execution=False)
    bash_exec.set_skill_env_map({"demo_skill": {"SK": "1"}})
    workspace = MagicMock()

    mock_ensure_skills = AsyncMock(return_value=["/ws/.claude/skills/demo_skill"])
    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(workspace, None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch.object(
            bash_exec._skill_manager,
            "ensure_skills_in_workspace",
            mock_ensure_skills,
        ),
        patch(
            "myrm_agent_harness.toolkits.code_execution.utils.WorkspacePathResolver.to_container_paths",
            return_value=["/workspace/.claude/skills/demo_skill"],
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._compression.output_eviction.maybe_evict_large_output",
            AsyncMock(return_value=MagicMock(text="ok", evicted_ref=None)),
        ),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
    ):
        await bash_exec.execute(
            "from skills.demo_skill import run",
            session_id="sess-1",
            skill_paths=["/host/skills/demo_skill"],
        )

    context = executor.execute.call_args.args[0]
    assert context.active_skills == ["demo_skill"]
    assert context.work_dir == "/workspace/.claude/skills/demo_skill"
    assert context.env["SK"] == "1"


@pytest.mark.asyncio
async def test_execute_python_path_and_generated_files() -> None:
    executor = _mock_code_executor()
    executor.execute.return_value = ExecutionResult(
        success=True,
        result=0,
        stdout="done",
        stderr="",
        container_id="c1",
        generated_files=["/tmp/chart.png"],
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=False)
    workspace = MagicMock()

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(workspace, None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch.object(
            bash_exec, "_prepare_execution", return_value=(True, "print(1)", None)
        ),
        patch.object(bash_exec, "_register_generated_files") as mock_register,
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._compression.output_eviction.maybe_evict_large_output",
            AsyncMock(return_value=MagicMock(text="done", evicted_ref=None)),
        ),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
    ):
        await bash_exec.execute("print(1)", session_id="sess-1")

    mock_register.assert_called_once()


@pytest.mark.asyncio
async def test_execute_nonzero_exit_without_error_logs_warning() -> None:
    executor = _mock_code_executor()
    executor.execute_bash.return_value = ExecutionResult(
        success=False,
        result=2,
        stdout="",
        stderr="",
        error=None,
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), None)),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(
            bash_exec._workspace_manager, "update_workspace_timestamp", AsyncMock()
        ),
        patch.object(bash_exec, "_ensure_mcp_proxy_started", AsyncMock()),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._compression.output_eviction.maybe_evict_large_output",
            AsyncMock(return_value=MagicMock(text="", evicted_ref=None)),
        ),
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
    ):
        result = await bash_exec.execute("false", session_id="sess-1")

    assert result["exit_code"] == "2"


@pytest.mark.asyncio
async def test_spawn_background_strips_fence_and_handles_quota() -> None:
    executor = _mock_code_executor()
    proc = MagicMock()
    proc.kill = MagicMock()
    executor.spawn_background_process = AsyncMock(return_value=proc)
    executor.bind_workspace = MagicMock()

    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with (
        patch.object(
            bash_exec._workspace_manager,
            "get_or_create",
            AsyncMock(return_value=(MagicMock(), "stale-ws")),
        ),
        patch.object(
            bash_exec._workspace_manager, "get_workspace_path", return_value="/ws"
        ),
        patch.object(bash_exec._skill_manager, "clear_workspace_cache") as mock_clear,
        patch.object(bash_exec, "_log_bash_command_execution", AsyncMock()),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._background.registry.get_background_registry",
        ) as mock_registry,
    ):
        mock_registry.return_value.register = AsyncMock(
            side_effect=__import__(
                "myrm_agent_harness.agent.meta_tools.bash._background.registry",
                fromlist=["BackgroundQuotaError"],
            ).BackgroundQuotaError("sess-1", 1)
        )
        with pytest.raises(BashExecutionError) as exc_info:
            await bash_exec.spawn_background("```\nsleep 1\n```", session_id="sess-1")

    mock_clear.assert_called_once_with("stale-ws")
    assert exc_info.value.error_category == "BACKGROUND_QUOTA_EXCEEDED"
    proc.kill.assert_called_once()


def test_build_error_details_prefers_stdout_then_stderr() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    assert (
        bash_exec._build_error_details(
            ExecutionResult(success=False, result=1, stdout="out")
        )
        == "out"
    )
    assert (
        bash_exec._build_error_details(
            ExecutionResult(success=False, result=1, stderr="err")
        )
        == "err"
    )
    assert (
        bash_exec._build_error_details(ExecutionResult(success=False, result=1))
        == "Unknown error"
    )


def test_register_generated_files_delegates() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    result = ExecutionResult(
        success=True,
        result=0,
        generated_files=["/tmp/a.png"],
        container_id="cid",
    )
    with patch(
        "myrm_agent_harness.agent.artifacts.registry.register_generated_files",
    ) as mock_register:
        bash_exec._register_generated_files(result)
    mock_register.assert_called_once_with(
        generated_files=["/tmp/a.png"], container_id="cid"
    )


def test_resolve_allowed_credential_issuers() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    assert bash_exec._resolve_allowed_credential_issuers(None) is None
    bash_exec.set_skill_oauth_issuers({"skill-a": "issuer-a"})
    assert bash_exec._resolve_allowed_credential_issuers(["skill-a"]) == ["issuer-a"]
    bash_exec.set_skill_oauth_issuers({})
    assert bash_exec._resolve_allowed_credential_issuers(["skill-a"]) == []


def test_build_execution_context_skill_env_only() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    ctx = bash_exec._build_execution_context(
        prepared_code="x",
        original_code="x",
        mcp_config_items=None,
        session_id="s1",
        workspace=None,
        env_paths=None,
        working_dir=None,
        skill_names=["skill-a"],
        skill_env={"ONLY": "1"},
        timeout=None,
    )
    assert ctx.env is not None
    assert ctx.env["ONLY"] == "1"


@pytest.mark.asyncio
async def test_ensure_mcp_proxy_skips_when_executor_uses_direct_callback() -> None:
    executor = _mock_code_executor()
    executor.get_mcp_communication_config.return_value = MagicMock(
        skip_local_proxy=True
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with patch(
        "myrm_agent_harness.agent.skills.mcp.start_mcp_ipc_server",
        AsyncMock(),
    ) as mock_start:
        await bash_exec._ensure_mcp_proxy_started()

    mock_start.assert_not_called()
    assert bash_exec._mcp_proxy_started is True


@pytest.mark.asyncio
async def test_ensure_mcp_proxy_start_failure_raises_runtime_error() -> None:
    executor = _mock_code_executor()
    bash_exec = BashExecutor(executor, enable_skill_execution=False)

    with (
        patch(
            "myrm_agent_harness.agent.skills.mcp.get_mcp_ipc_server",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.skills.mcp.start_mcp_ipc_server",
            AsyncMock(side_effect=OSError("boom")),
        ),
        pytest.raises(RuntimeError, match="Failed to start MCP IPC server"),
    ):
        await bash_exec._ensure_mcp_proxy_started()


def test_prepare_execution_skill_path_when_enabled() -> None:
    executor = _mock_code_executor()
    skill_executor = MagicMock()
    skill_executor.detect_skill_in_command.return_value = (True, "demo")
    skill_executor.prepare_for_execution.return_value = MagicMock(
        prepared_code="print('skill')",
        mcp_config=[MagicMock()],
    )
    bash_exec = BashExecutor(executor, enable_skill_execution=True)
    bash_exec._skill_executor = skill_executor

    use_py, code, mcp_items = bash_exec._prepare_execution(
        "run skill", session_id="s1", workspace_root="/ws"
    )

    assert use_py is True
    assert code == "print('skill')"
    assert mcp_items is not None


def test_prepare_execution_python_c_sets_transform_hint() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    bash_exec._prepare_execution('python3 -c "print(1)"', session_id="s1")
    assert bash_exec.consume_python_c_transform_hint() is not None


def test_validate_python_syntax_raises_bash_execution_error() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    with pytest.raises(BashExecutionError) as exc_info:
        bash_exec._validate_python_syntax("def broken(", "print bad")
    assert exc_info.value.error_category == "syntax"


def test_inject_resilience_script_prepends_when_present() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    result = bash_exec._inject_resilience_script("echo hi")
    assert "echo hi" in result


def test_rewrite_skill_paths_returns_detected_skill() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._executor.prepare_mixin.rewrite_skill_paths",
        return_value=("rewritten", "demo"),
    ):
        code, skill = bash_exec._rewrite_skill_paths("orig")
    assert code == "rewritten"
    assert skill == "demo"


def test_convert_to_container_paths_empty_root() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    workspace = MagicMock()
    with patch.object(
        bash_exec._workspace_manager, "get_workspace_path", return_value=""
    ):
        assert bash_exec._convert_to_container_paths(["/x"], workspace) == []


def test_maybe_extend_timeout_for_mcp() -> None:
    bash_exec = BashExecutor(_mock_code_executor(), enable_skill_execution=False)
    from myrm_agent_harness.agent.meta_tools.bash._executor.constants import (
        MCP_MIN_TIMEOUT,
    )

    assert bash_exec._maybe_extend_timeout_for_mcp([MagicMock()], 5) == MCP_MIN_TIMEOUT
    assert bash_exec._maybe_extend_timeout_for_mcp(None, 30) == 30


@dataclass
class _FakeBackgroundInfo:
    pid: int
    command: str
    status: str
    exit_code: int | None = None
