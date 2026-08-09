from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
    create_bash_code_execute_tool,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_executor import BashExecutionError
from myrm_agent_harness.utils.errors import ToolError


def _patch_bash_tool_deps():
    """Return a combined context manager that mocks executor + context deps."""
    mock_executor = MagicMock()
    mock_executor.get_executor_name.return_value = "test"

    mock_bash_executor = AsyncMock()
    mock_bash_executor.set_skill_oauth_issuers = MagicMock()
    mock_bash_executor.set_skill_env_map = MagicMock()
    mock_bash_executor.set_global_env = MagicMock()
    mock_bash_executor.consume_python_c_transform_hint = MagicMock(return_value=None)

    return (
        mock_bash_executor,
        patch(
            "myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool.extract_context_from_runnable_config",
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
            "myrm_agent_harness.agent.skills.mcp.notify_registry.session_scope",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=False),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_bash_tool_myrm_tools_preflight_blocks_before_executor() -> None:
    """Preflight wiring: import myrm_tools must not reach BashExecutor."""
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with pytest.raises(ToolError, match="myrm_tools") as exc_info:
            await tool.ainvoke(
                {
                    "command": "import myrm_tools\nprint('x')",
                    "reason": "verify myrm_tools preflight blocks before sandbox execution",
                }
            )

    mock_bash_exec.execute.assert_not_called()
    assert exc_info.value.error_code == "MYRM_TOOLS_BLOCKED"
    assert exc_info.value.error_category == ToolErrorCategory.GUARDRAIL_BLOCKED.value


@pytest.mark.asyncio
async def test_bash_tool_myrm_tools_pipe_preflight_blocks_before_executor() -> None:
    """Pipe stdin myrm_tools must not reach BashExecutor."""
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with pytest.raises(ToolError, match="myrm_tools") as exc_info:
            await tool.ainvoke(
                {
                    "command": 'printf "import myrm_tools" | python3',
                    "reason": "verify pipe stdin myrm_tools preflight blocks before sandbox execution",
                }
            )

    mock_bash_exec.execute.assert_not_called()
    assert exc_info.value.error_code == "MYRM_TOOLS_BLOCKED"
    assert exc_info.value.error_category == ToolErrorCategory.GUARDRAIL_BLOCKED.value


@pytest.mark.asyncio
async def test_bash_tool_myrm_tools_python_m_preflight_blocks_before_executor() -> None:
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with pytest.raises(ToolError, match="myrm_tools") as exc_info:
            await tool.ainvoke(
                {
                    "command": "python3 -m myrm_tools",
                    "reason": "verify python -m myrm_tools preflight blocks before sandbox execution",
                }
            )

    mock_bash_exec.execute.assert_not_called()
    assert exc_info.value.error_code == "MYRM_TOOLS_BLOCKED"


@pytest.mark.asyncio
async def test_bash_tool_myrm_tools_cat_pipe_preflight_blocks_before_executor(
    tmp_path: Path,
) -> None:
    script_path = tmp_path / "merge.py"
    script_path.write_text("import myrm_tools\n", encoding="utf-8")
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()

    with p_ctx as mock_ctx, p_get, p_be, p_scope:
        mock_ctx.return_value = {
            "session_id": "test-session",
            "workspace_root": str(tmp_path),
        }
        tool = create_bash_code_execute_tool()
        with pytest.raises(ToolError, match="myrm_tools") as exc_info:
            await tool.ainvoke(
                {
                    "command": f"cat {script_path} | python3",
                    "reason": "verify cat pipe myrm_tools preflight blocks before sandbox execution",
                }
            )

    mock_bash_exec.execute.assert_not_called()
    assert exc_info.value.error_code == "MYRM_TOOLS_BLOCKED"


@pytest.mark.asyncio
async def test_bash_tool_git_clone_hint():
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()
    mock_bash_exec.execute.side_effect = BashExecutionError(
        "Command timed out", phase="execution"
    )

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke(
                {
                    "command": "git clone https://github.com/owner/repo.git",
                    "reason": "test cloning from remote repo",
                }
            )

        assert "git clone" in exc_info.value.user_hint
        assert "curl" in exc_info.value.user_hint
        assert "Diagnostic Hint" in exc_info.value.user_hint


@pytest.mark.asyncio
async def test_bash_tool_no_git_clone_hint_for_other_commands():
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()
    mock_bash_exec.execute.side_effect = BashExecutionError(
        "Command timed out", phase="execution"
    )

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke(
                {"command": "ls -la", "reason": "test cloning from remote repo"}
            )

        assert "git clone" not in exc_info.value.user_hint
        assert "curl" not in exc_info.value.user_hint


@pytest.mark.asyncio
async def test_bash_tool_failure_emits_stderr_evicted_ref():
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()
    mock_bash_exec.execute.side_effect = BashExecutionError(
        "ValueError: bad row 150",
        phase="execution",
        stderr_evicted_ref="output_fail123.txt",
        stderr_evicted_stored_chars=1500,
        stderr_evicted_total_lines=12,
        stderr_evicted_storage_truncated=False,
    )

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with (
            patch(
                "myrm_agent_harness.agent.context_management.infra.evicted_content.emit_evicted_ref",
                new=AsyncMock(),
            ) as mock_emit,
            pytest.raises(ToolError) as exc_info,
        ):
            await tool.ainvoke(
                {"command": "ls -la", "reason": "verify failure eviction emit"}
            )

    assert str(exc_info.value) == "ValueError: bad row 150"
    mock_emit.assert_awaited_once()
    call = mock_emit.await_args
    assert call.args[0] == "output_fail123.txt"
    kwargs = call.kwargs
    assert kwargs["stream"] == "stderr"
    assert kwargs["stored_chars"] == 1500
    assert kwargs["total_lines"] == 12


@pytest.mark.asyncio
async def test_bash_tool_failure_emits_both_streams_evicted_refs():
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()
    mock_bash_exec.execute.side_effect = BashExecutionError(
        "ValueError: bad row 150",
        phase="execution",
        stdout_evicted_ref="stdout_out_1.txt",
        stdout_evicted_stored_chars=32,
        stdout_evicted_total_lines=1,
        stdout_evicted_storage_truncated=False,
        stderr_evicted_ref="output_fail123.txt",
        stderr_evicted_stored_chars=1500,
        stderr_evicted_total_lines=12,
        stderr_evicted_storage_truncated=False,
    )

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with (
            patch(
                "myrm_agent_harness.agent.context_management.infra.evicted_content.emit_evicted_ref",
                new=AsyncMock(),
            ) as mock_emit,
            pytest.raises(ToolError),
        ):
            await tool.ainvoke(
                {"command": "ls -la", "reason": "verify both-stream eviction emit"}
            )

    calls = mock_emit.await_args_list
    assert len(calls) == 2
    stdout_call, stderr_call = calls
    assert stdout_call.args[0] == "stdout_out_1.txt"
    assert stdout_call.kwargs["stream"] == "stdout"
    assert stdout_call.kwargs["stored_chars"] == 32
    assert stderr_call.args[0] == "output_fail123.txt"
    assert stderr_call.kwargs["stream"] == "stderr"
    assert stderr_call.kwargs["stored_chars"] == 1500
    assert stderr_call.kwargs["total_lines"] == 12


@pytest.mark.asyncio
async def test_bash_tool_failure_carries_error_category_diagnostic() -> None:
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()
    mock_bash_exec.execute.side_effect = BashExecutionError(
        "ValueError: bad row 150",
        phase="execution",
        error_category="EXEC",
    )

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke(
                {"command": "ls -la", "reason": "verify diagnostic category"}
            )

    assert exc_info.value.diagnostic_info == {"error_category": "EXEC"}


@pytest.mark.asyncio
async def test_bash_tool_emit_failure_does_not_mask_original_error() -> None:
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()
    mock_bash_exec.execute.side_effect = BashExecutionError(
        "ValueError: bad row 150",
        phase="execution",
        stderr_evicted_ref="output_fail123.txt",
        stderr_evicted_stored_chars=1500,
        stderr_evicted_total_lines=12,
        stderr_evicted_storage_truncated=False,
    )

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with (
            patch(
                "myrm_agent_harness.agent.context_management.infra.evicted_content.emit_evicted_ref",
                new=AsyncMock(side_effect=RuntimeError("emit down")),
            ),
            pytest.raises(ToolError) as exc_info,
        ):
            await tool.ainvoke(
                {"command": "ls -la", "reason": "verify emit failure isolation"}
            )

    assert str(exc_info.value) == "ValueError: bad row 150"


@pytest.mark.asyncio
async def test_bash_tool_success_emits_stderr_evicted_ref() -> None:
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()
    mock_bash_exec.execute.return_value = {
        "stdout": "ok",
        "stderr": "",
        "exit_code": "0",
        "mcp_metadata": None,
        "generated_files": [],
        "stderr_evicted_ref": "stderr_out_1.txt",
        "stderr_evicted_stored_chars": 2048,
        "stderr_evicted_total_lines": 100,
        "stderr_evicted_storage_truncated": False,
    }

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with patch(
            "myrm_agent_harness.agent.context_management.infra.evicted_content.emit_evicted_ref",
            new=AsyncMock(),
        ) as mock_emit:
            await tool.ainvoke(
                {"command": "ls -la", "reason": "verify success-path stderr emit"}
            )

    mock_emit.assert_awaited_once()
    call = mock_emit.await_args
    assert call.args[0] == "stderr_out_1.txt"
    assert call.kwargs["stream"] == "stderr"
    assert call.kwargs["stored_chars"] == 2048
    assert call.kwargs["total_lines"] == 100
    assert call.kwargs["storage_truncated"] is False


def test_mcp_min_timeout_constant_exceeds_ipc_client() -> None:
    """_MCP_MIN_TIMEOUT must be > IPC client TOTAL_TIMEOUT (90s)."""
    from myrm_agent_harness.agent.meta_tools.bash.bash_executor import _MCP_MIN_TIMEOUT
    from myrm_agent_harness.agent.skills.mcp.client_templates import TOTAL_TIMEOUT

    assert _MCP_MIN_TIMEOUT > TOTAL_TIMEOUT


def test_mcp_min_timeout_is_120() -> None:
    from myrm_agent_harness.agent.meta_tools.bash.bash_executor import _MCP_MIN_TIMEOUT

    assert _MCP_MIN_TIMEOUT == 120
