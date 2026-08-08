from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import create_bash_code_execute_tool
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
async def test_bash_tool_myrm_tools_cat_pipe_preflight_blocks_before_executor(tmp_path: Path) -> None:
    script_path = tmp_path / "merge.py"
    script_path.write_text("import myrm_tools\n", encoding="utf-8")
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()

    with p_ctx as mock_ctx, p_get, p_be, p_scope:
        mock_ctx.return_value = {"session_id": "test-session", "workspace_root": str(tmp_path)}
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
        "Command timed out", phase="execution", command="git clone"
    )

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke(
                {"command": "git clone https://github.com/owner/repo.git", "reason": "test cloning from remote repo"}
            )

        assert "git clone" in exc_info.value.user_hint
        assert "curl" in exc_info.value.user_hint
        assert "Diagnostic Hint" in exc_info.value.user_hint


@pytest.mark.asyncio
async def test_bash_tool_no_git_clone_hint_for_other_commands():
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()
    mock_bash_exec.execute.side_effect = BashExecutionError(
        "Command timed out", phase="execution", command="ls -la"
    )

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_code_execute_tool()
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke({"command": "ls -la", "reason": "test cloning from remote repo"})

        assert "git clone" not in exc_info.value.user_hint
        assert "curl" not in exc_info.value.user_hint


def test_mcp_min_timeout_constant_exceeds_ipc_client() -> None:
    """_MCP_MIN_TIMEOUT must be > IPC client TOTAL_TIMEOUT (90s)."""
    from myrm_agent_harness.agent.meta_tools.bash.bash_executor import _MCP_MIN_TIMEOUT
    from myrm_agent_harness.agent.skills.mcp.client_templates import TOTAL_TIMEOUT

    assert _MCP_MIN_TIMEOUT > TOTAL_TIMEOUT


def test_mcp_min_timeout_is_120() -> None:
    from myrm_agent_harness.agent.meta_tools.bash.bash_executor import _MCP_MIN_TIMEOUT

    assert _MCP_MIN_TIMEOUT == 120
