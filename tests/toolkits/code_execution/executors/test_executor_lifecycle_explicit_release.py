from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.base import (
    CodeExecutor,
    CodeExecutorMiddleware,
    clear_and_close_stashed_executor,
    clear_stashed_executor,
    get_stashed_executor,
    stash_executor_for_session,
)
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.appcontainer import AppContainerProvider
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.bwrap import BwrapProvider
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.null import NullProvider
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.seatbelt import SeatbeltProvider
from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import SandboxProvider


class _DummyExecutor(CodeExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    async def execute(self, context):
        raise NotImplementedError

    async def execute_bash(self, context):
        raise NotImplementedError

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_code_executor_async_context_manager() -> None:
    executor = _DummyExecutor()
    assert not executor.closed
    async with executor as exc:
        assert exc is executor
    assert executor.closed


@pytest.mark.asyncio
async def test_code_executor_middleware_close_delegation() -> None:
    inner = _DummyExecutor()
    middleware = CodeExecutorMiddleware(inner)
    assert not inner.closed
    await middleware.close()
    assert inner.closed


@pytest.mark.asyncio
async def test_local_executor_close_idempotency() -> None:
    config = ExecutionConfig()
    executor = LocalExecutor(config)

    mock_session = AsyncMock()
    executor._bash_sessions["session_1"] = mock_session

    assert not executor._closed
    await executor.close()
    assert executor._closed
    mock_session.close.assert_awaited_once()
    assert "session_1" not in executor._bash_sessions

    # Idempotent second close
    await executor.close()
    assert mock_session.close.await_count == 1


@pytest.mark.asyncio
async def test_stashed_executor_clear_and_close() -> None:
    executor = _DummyExecutor()
    session_id = "test-session-lifecycle"

    stash_executor_for_session(session_id, executor)
    assert get_stashed_executor(session_id) is executor

    await clear_and_close_stashed_executor(session_id)
    assert get_stashed_executor(session_id) is None
    assert executor.closed


@pytest.mark.asyncio
async def test_stashed_executor_sync_clear_schedules_close() -> None:
    executor = _DummyExecutor()
    session_id = "test-session-sync-clear"

    stash_executor_for_session(session_id, executor)
    assert get_stashed_executor(session_id) is executor

    clear_stashed_executor(session_id)
    assert get_stashed_executor(session_id) is None


def test_sandbox_providers_cleanup_protocol() -> None:
    for provider in (NullProvider(), BwrapProvider(), SeatbeltProvider()):
        assert isinstance(provider, SandboxProvider)
        # Verify cleanup method exists and can be called safely
        provider.cleanup()


def test_appcontainer_provider_cleanup_sync_safety() -> None:
    provider = AppContainerProvider()
    provider._container_sid = "S-1-15-2-12345"
    provider._acl_paths = [("/tmp/nonexistent_path_for_test", "")]

    with patch("myrm_agent_harness.toolkits.code_execution.sandbox.providers.appcontainer._remove_acl_sync") as mock_remove:
        with patch("os.path.exists", return_value=True):
            provider.cleanup()
        mock_remove.assert_called_once_with("/tmp/nonexistent_path_for_test", "S-1-15-2-12345")
