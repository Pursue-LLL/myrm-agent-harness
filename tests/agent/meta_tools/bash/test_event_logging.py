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
    from myrm_agent_harness.agent.meta_tools.bash._event_logging import (
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
    from myrm_agent_harness.agent.meta_tools.bash._event_logging import (
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
    from myrm_agent_harness.agent.meta_tools.bash._event_logging import (
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


@pytest.mark.asyncio
async def test_log_bash_command_execution_exception_safe() -> None:
    """If logging raises, function catches silently (failure-safe)."""
    from myrm_agent_harness.agent.meta_tools.bash._event_logging import (
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
