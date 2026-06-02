from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.code_execution.executors.base import ExecutionContext, ExecutionResult
from myrm_agent_harness.toolkits.code_execution.executors.readonly_proxy import ReadonlyExecutorProxy


@pytest.fixture
def mock_inner_executor():
    inner = AsyncMock()
    inner.execute = AsyncMock(return_value=ExecutionResult(success=True))
    inner.execute_bash = AsyncMock(return_value=ExecutionResult(success=True))
    inner.execute_bash_stream = AsyncMock()
    return inner

@pytest.fixture
def proxy(mock_inner_executor):
    return ReadonlyExecutorProxy(mock_inner_executor)

@pytest.mark.asyncio
async def test_readonly_proxy_file_writes(proxy, mock_inner_executor):
    with pytest.raises(PermissionError, match="Write denied"):
        await proxy.write_file("test.txt", "content")

    with pytest.raises(PermissionError, match="Write denied"):
        await proxy.write_file_atomic("test.txt", "content")

    with pytest.raises(PermissionError, match="Write denied"):
        await proxy.write_file_bytes_atomic("test.txt", b"content")

    with pytest.raises(PermissionError, match="Write denied"):
        await proxy.write_file_bytes("test.txt", b"content")

    with pytest.raises(PermissionError, match="Write denied"):
        await proxy.append_file("test.txt", "content")

    with pytest.raises(PermissionError, match="Delete denied"):
        await proxy.delete_file("test.txt")

    with pytest.raises(PermissionError, match="Mkdir denied"):
        await proxy.mkdir("test_dir")

    ctx = ExecutionContext(code="echo 1", session_id="session1")
    result = await proxy.execute(ctx)

    assert mock_inner_executor.execute.called
    called_ctx = mock_inner_executor.execute.call_args[0][0]
    assert called_ctx.readonly_workspace is True
    assert called_ctx.session_id == "session1_readonly"
    assert result.success is True

@pytest.mark.asyncio
@patch("myrm_agent_harness.toolkits.code_execution.sandbox.detect_sandbox_provider")
async def test_execute_bash_sandbox_enabled(mock_detect, proxy, mock_inner_executor):
    mock_provider = AsyncMock()
    mock_status = AsyncMock()
    mock_status.enabled = True
    mock_detect.return_value = (mock_provider, mock_status)

    ctx = ExecutionContext(code="echo 1", session_id="session1")
    result = await proxy.execute_bash(ctx)

    assert mock_inner_executor.execute_bash.called
    called_ctx = mock_inner_executor.execute_bash.call_args[0][0]
    assert called_ctx.readonly_workspace is True
    assert called_ctx.session_id == "session1_readonly"
    assert result.success is True

@pytest.mark.asyncio
@patch("myrm_agent_harness.toolkits.code_execution.sandbox.detect_sandbox_provider")
async def test_execute_bash_sandbox_disabled(mock_detect, proxy, mock_inner_executor):
    mock_provider = AsyncMock()
    mock_status = AsyncMock()
    mock_status.enabled = False
    mock_detect.return_value = (mock_provider, mock_status)

    ctx = ExecutionContext(code="echo 1")
    result = await proxy.execute_bash(ctx)

    assert not mock_inner_executor.execute_bash.called
    assert result.success is False
    assert "Bash execution is strictly disabled" in result.error
    assert result.exit_code == 1
