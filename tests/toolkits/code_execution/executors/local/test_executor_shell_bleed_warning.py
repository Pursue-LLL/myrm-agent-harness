"""Tests for LocalExecutor integration with shell_bleed warning scanner.

Verifies that when bash commands or python code reference sensitive environment variables
(e.g., $OPENAI_API_KEY, os.environ["AWS_SECRET_ACCESS_KEY"]), the warning scanner triggers
a structured audit warning without breaking execution flow.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext, ExecutionResult


@pytest.mark.asyncio
async def test_local_executor_bash_shell_bleed_warning():
    """Verify that referencing sensitive env in bash command triggers audit warning."""
    executor = LocalExecutor(ExecutionConfig())
    context = ExecutionContext(
        session_id="test_session",
        code="echo $OPENAI_API_KEY",
        timeout=10,
    )

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(success=True, stdout="output\n", stderr="", exit_code=0)
    )

    with patch(
        "myrm_agent_harness.toolkits.code_execution.executors.local.executor.logger.warning"
    ) as mock_warning, patch.object(
        executor, "_get_or_create_bash_session", new_callable=AsyncMock
    ) as mock_get_session:
        mock_get_session.return_value = mock_session

        result = await executor.execute_bash(context)

        assert result.success
        # Verify logger.warning was called for shell bleed
        warning_calls = [str(call) for call in mock_warning.call_args_list]
        assert any("Shell bleed warning" in call and "OPENAI_API_KEY" in call for call in warning_calls)


@pytest.mark.asyncio
async def test_local_executor_python_env_leak_warning():
    """Verify that referencing sensitive env in python code triggers audit warning."""
    executor = LocalExecutor(ExecutionConfig())
    code = "import os\nkey = os.environ['AWS_SECRET_ACCESS_KEY']\n"
    context = ExecutionContext(
        session_id="test_session",
        code=code,
        timeout=10,
    )

    with patch(
        "myrm_agent_harness.toolkits.code_execution.executors.local.executor.logger.warning"
    ) as mock_warning, patch.object(
        executor, "_run_subprocess", new_callable=AsyncMock
    ) as mock_subproc:
        mock_subproc.return_value = ExecutionResult(
            success=True,
            stdout="",
            stderr="",
            execution_time=0.1,
        )

        result = await executor.execute(context)

        assert result.success
        # Verify logger.warning was called for python env leak
        warning_calls = [str(call) for call in mock_warning.call_args_list]
        assert any("Python env leak warning" in call and "AWS_SECRET_ACCESS_KEY" in call for call in warning_calls)
