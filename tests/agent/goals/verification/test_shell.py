from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.goals.verification.shell import ShellCriterion
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionResult


@pytest.fixture
def mock_executor():
    with patch("myrm_agent_harness.agent.goals.verification.shell.get_executor") as mock_get:
        executor = AsyncMock()
        mock_get.return_value = executor
        yield executor

@pytest.mark.asyncio
async def test_shell_criterion_success(mock_executor):
    mock_executor.execute_bash.return_value = ExecutionResult(
        exit_code=0, stdout="success", stderr=""
    )

    criterion = ShellCriterion(command="echo success")
    result = await criterion.verify()

    assert result.passed is True
    mock_executor.execute_bash.assert_called_once()
    context = mock_executor.execute_bash.call_args[0][0]
    assert context.code == "echo success"
    assert context.timeout == 60

@pytest.mark.asyncio
async def test_shell_criterion_failure(mock_executor):
    mock_executor.execute_bash.return_value = ExecutionResult(
        exit_code=1, stdout="", stderr="command not found"
    )

    criterion = ShellCriterion(command="invalid_cmd")
    result = await criterion.verify()

    assert result.passed is False
    assert "invalid_cmd" in result.reason
    assert "command not found" in result.error_logs

@pytest.mark.asyncio
async def test_shell_criterion_no_executor():
    with patch("myrm_agent_harness.agent.goals.verification.shell.get_executor", return_value=None):
        criterion = ShellCriterion(command="echo success")
        result = await criterion.verify()

        assert result.passed is False
        assert "Sandbox executor not found" in result.reason

def test_shell_criterion_from_dict():
    data = {"type": "shell", "command": "pytest", "timeout_seconds": 120}
    criterion = ShellCriterion.from_dict(data)
    assert criterion.command == "pytest"
    assert criterion.timeout_seconds == 120
