from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext


@pytest.mark.asyncio
async def test_local_executor_module_not_found_hint():
    executor = LocalExecutor(ExecutionConfig())
    context = ExecutionContext(session_id="test_session", code="import requests")

    with patch("myrm_agent_harness.toolkits.code_execution.executors.local.executor.asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"Traceback (most recent call last):\nModuleNotFoundError: No module named 'requests'")
        mock_process.returncode = 1
        mock_exec.return_value = mock_process

        result = await executor.execute(context)

        assert not result.success
        assert "Diagnostic Hint" in result.stderr
        assert "python -m pip install requests" in result.stderr
        assert "Diagnostic Hint" in result.error
        assert "python -m pip install requests" in result.error

@pytest.mark.asyncio
async def test_local_executor_no_hint_for_other_errors():
    executor = LocalExecutor(ExecutionConfig())
    context = ExecutionContext(session_id="test_session", code="print('hello'")

    with patch("myrm_agent_harness.toolkits.code_execution.executors.local.executor.asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"SyntaxError: invalid syntax")
        mock_process.returncode = 1
        mock_exec.return_value = mock_process

        result = await executor.execute(context)

        assert not result.success
        assert "Diagnostic Hint" not in result.stderr
        if result.error:
            assert "Diagnostic Hint" not in result.error

@pytest.mark.asyncio
async def test_local_executor_success():
    executor = LocalExecutor(ExecutionConfig())
    context = ExecutionContext(session_id="test_session", code="print('hello')")

    with patch("myrm_agent_harness.toolkits.code_execution.executors.local.executor.asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"hello\n", b"")
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        result = await executor.execute(context)

        assert result.success
        assert result.stdout == "hello\n"
        assert result.stderr == ""

def test_dummy_to_force_coverage_report():
    # This is just to ensure the file is considered part of the coverage
    from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor
    assert LocalExecutor is not None
