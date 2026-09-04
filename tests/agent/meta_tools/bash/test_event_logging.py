"""Tests for _event_logging.py — bash command event logging.

Verifies the failure-safe logging function handles both
normal and error scenarios without affecting the main flow.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

_PATCH_GET_LOGGER = "myrm_agent_harness.agent.middlewares._session_context.get_event_logger"


@pytest.mark.asyncio
async def test_log_bash_command_execution_no_logger() -> None:
    """When no event logger is available, function returns silently."""
    from myrm_agent_harness.agent.meta_tools.bash._executor.event_logging import (
        log_bash_command_execution,
    )

    with patch(_PATCH_GET_LOGGER, return_value=None):
        await log_bash_command_execution(
            command="echo hello",
            session_id="test-session",
            exit_code=0,
            stdout="hello",
            stderr="",
            duration_ms=100,
            success=True,
        )


@pytest.mark.asyncio
async def test_log_bash_command_execution_with_logger() -> None:
    """When event logger is available, function logs the event."""
    from myrm_agent_harness.agent.meta_tools.bash._executor.event_logging import (
        log_bash_command_execution,
    )

    mock_logger = AsyncMock()
    mock_logger.log = AsyncMock()

    with patch(_PATCH_GET_LOGGER, return_value=mock_logger):
        await log_bash_command_execution(
            command="git status",
            session_id="test-session",
            exit_code=0,
            stdout="On branch main",
            stderr="",
            duration_ms=50,
            success=True,
        )

    mock_logger.log.assert_called_once()
    call_args = mock_logger.log.call_args
    assert call_args[0][0] == "bash_command_executed"
    event_data = call_args[0][1]
    assert event_data["exit_code"] == 0
    assert event_data["success"] is True
    assert event_data["duration_ms"] == 50


@pytest.mark.asyncio
async def test_log_bash_command_execution_with_error() -> None:
    """When event logger is available and command failed, error_message is included."""
    from myrm_agent_harness.agent.meta_tools.bash._executor.event_logging import (
        log_bash_command_execution,
    )

    mock_logger = AsyncMock()
    mock_logger.log = AsyncMock()

    with patch(_PATCH_GET_LOGGER, return_value=mock_logger):
        await log_bash_command_execution(
            command="rm -rf /",
            session_id="test-session",
            exit_code=1,
            stdout="",
            stderr="Permission denied",
            duration_ms=10,
            success=False,
            error_message="Operation not permitted",
        )

    event_data = mock_logger.log.call_args[0][1]
    assert event_data["success"] is False
    assert event_data["error_message"] == "Operation not permitted"


@patch(
    "myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer.get_current_message_id",
    return_value="msg-42",
)
@pytest.mark.asyncio
async def test_log_bash_command_execution_includes_message_id(mock_msg_id) -> None:
    """When a turn-level message id is available, it is attached to the event."""
    from myrm_agent_harness.agent.meta_tools.bash._executor.event_logging import (
        log_bash_command_execution,
    )

    mock_logger = AsyncMock()
    mock_logger.log = AsyncMock()

    with patch(_PATCH_GET_LOGGER, return_value=mock_logger):
        await log_bash_command_execution(
            command="git log --oneline",
            session_id="test-session",
            exit_code=0,
            stdout="abc123",
            stderr="",
            duration_ms=40,
            success=True,
        )

    event_data = mock_logger.log.call_args[0][1]
    assert event_data["message_id"] == "msg-42"


@patch(
    "myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer.get_current_message_id",
    return_value=None,
)
@pytest.mark.asyncio
async def test_log_bash_command_execution_omits_message_id_when_absent(mock_msg_id) -> None:
    """When no turn message id is active, the event carries no message_id field."""
    from myrm_agent_harness.agent.meta_tools.bash._executor.event_logging import (
        log_bash_command_execution,
    )

    mock_logger = AsyncMock()
    mock_logger.log = AsyncMock()

    with patch(_PATCH_GET_LOGGER, return_value=mock_logger):
        await log_bash_command_execution(
            command="echo hi",
            session_id="test-session",
            exit_code=0,
            stdout="hi",
            stderr="",
            duration_ms=5,
            success=True,
        )

    event_data = mock_logger.log.call_args[0][1]
    assert "message_id" not in event_data


@pytest.mark.asyncio
async def test_log_bash_command_execution_exception_safe() -> None:
    """If logging raises, function catches silently (failure-safe)."""
    from myrm_agent_harness.agent.meta_tools.bash._executor.event_logging import (
        log_bash_command_execution,
    )

    with patch(_PATCH_GET_LOGGER, side_effect=RuntimeError("Boom")):
        await log_bash_command_execution(
            command="echo test",
            session_id="test-session",
            exit_code=0,
            stdout="test",
            stderr="",
            duration_ms=5,
            success=True,
        )


@pytest.mark.asyncio
async def test_log_bash_command_execution_redacts_credentials_in_streams() -> None:
    """Verify that credentials in stdout/stderr/error_message are redacted."""
    from myrm_agent_harness.agent.meta_tools.bash._executor.event_logging import (
        log_bash_command_execution,
    )

    mock_logger = AsyncMock()
    mock_logger.log = AsyncMock()

    with patch(_PATCH_GET_LOGGER, return_value=mock_logger):
        await log_bash_command_execution(
            command="echo sk-ant-api03-abcdefghijklmnop1234567890",
            session_id="test-session",
            exit_code=1,
            stdout="Returned token: sk-ant-api03-abcdefghijklmnop1234567890",
            stderr="Error with token ghp_abcdefghijklmnop12345678901234567890",
            duration_ms=10,
            success=False,
            error_message="Failed key: xoxb-TESTING_MOCK_TOKEN_NOT_REAL_SECRET_123",
        )

    event_data = mock_logger.log.call_args[0][1]
    assert "sk-ant-api03" not in event_data["command"]
    assert "sk-ant-api03" not in event_data["stdout"]
    assert "ghp_abcdefghijklmnop12345678901234567890" not in event_data["stderr"]
    assert "xoxb-TESTING" not in event_data["error_message"]
    assert "..." in event_data["stdout"] or "***" in event_data["stdout"]

