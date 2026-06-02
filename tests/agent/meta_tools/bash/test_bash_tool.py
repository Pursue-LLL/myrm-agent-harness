from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash.bash_executor import BashExecutionError
from myrm_agent_harness.agent.meta_tools.bash.bash_tool import create_bash_tool
from myrm_agent_harness.utils.errors import ToolError


def _patch_bash_tool_deps():
    """Return a combined context manager that mocks executor + context deps."""
    mock_executor = MagicMock()
    mock_executor.get_executor_name.return_value = "test"

    mock_bash_executor = AsyncMock()
    mock_bash_executor.set_skill_env_map = MagicMock()
    mock_bash_executor.set_global_env = MagicMock()

    return (
        mock_bash_executor,
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
            "myrm_agent_harness.agent.skills.mcp.notify_registry.session_scope",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=False),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_bash_tool_git_clone_hint():
    mock_bash_exec, p_ctx, p_get, p_be, p_scope = _patch_bash_tool_deps()
    mock_bash_exec.execute.side_effect = BashExecutionError(
        "Command timed out", phase="execution", command="git clone"
    )

    with p_ctx, p_get, p_be, p_scope:
        tool = create_bash_tool()
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke(
                {"command": "git clone https://github.com/owner/repo.git", "reason": "test"}
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
        tool = create_bash_tool()
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke({"command": "ls -la", "reason": "test"})

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
