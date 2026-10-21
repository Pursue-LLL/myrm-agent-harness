"""Edge-path tests for tool interceptor middleware (compaction, clarification, cancellation)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware import (
    _extract_failure_metadata,
    _get_tool_args,
    _loop_kind_from_exception,
    _tool_interceptor_middleware_inner,
    notify_loop_guard_compaction,
)
from myrm_agent_harness.core.security.types import ToolClarificationError


def _request() -> MagicMock:
    request = MagicMock()
    request.tool_call = {"name": "test_tool", "args": {}, "id": "call_123"}
    return request


async def _noop_handler(_req: object) -> ToolMessage:
    raise AssertionError("handler must not run; execute_with_retry is mocked")


class TestNotifyLoopGuardCompaction:
    def test_contextvar_has_guard(self) -> None:
        guard = MagicMock()
        guard._metrics.total_calls = 5
        with (
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware._loop_guard_var"
            ) as mock_var,
            patch("myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.logger"),
        ):
            mock_var.get.return_value = guard
            notify_loop_guard_compaction()
        guard.notify_compaction.assert_called_once()

    def test_contextvar_none_falls_back_to_session(self) -> None:
        guard = MagicMock()
        guard._metrics.total_calls = 0
        with (
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware._loop_guard_var"
            ) as mock_var,
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware._get_session_loop_guard",
                return_value=guard,
            ) as mock_session,
        ):
            mock_var.get.return_value = None
            notify_loop_guard_compaction()
        mock_session.assert_called_once()
        guard.notify_compaction.assert_called_once()

    def test_no_guard_returns(self) -> None:
        with (
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware._loop_guard_var"
            ) as mock_var,
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware._get_session_loop_guard",
                return_value=None,
            ),
        ):
            mock_var.get.return_value = None
            notify_loop_guard_compaction()

    def test_lookup_error_returns(self) -> None:
        with (
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware._loop_guard_var"
            ) as mock_var,
        ):
            mock_var.get.side_effect = LookupError
            notify_loop_guard_compaction()


class TestExtractFailureMetadata:
    def test_non_tool_message_returns_none_none(self) -> None:
        assert _extract_failure_metadata(object()) == (None, None)

    def test_extracts_category_and_loop_kind(self) -> None:
        msg = ToolMessage(
            content="err",
            name="t",
            tool_call_id="c",
            additional_kwargs={"error_category": "loop", "loop_kind": "repeated"},
        )
        assert _extract_failure_metadata(msg) == ("loop", "repeated")

    def test_non_string_kwargs_ignored(self) -> None:
        msg = ToolMessage(
            content="err",
            name="t",
            tool_call_id="c",
            additional_kwargs={"error_category": 123, "loop_kind": None},
        )
        assert _extract_failure_metadata(msg) == (None, None)


class TestLoopKindFromException:
    def test_non_stuck_exception_returns_none(self) -> None:
        assert _loop_kind_from_exception(ValueError("x")) is None

    def test_stuck_exception_returns_kind(self) -> None:
        exc = type("ToolStuckException", (Exception,), {})("ToolStuckException")
        with patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.get_loop_guard"
        ) as mock_get:
            guard = MagicMock()
            guard.last_detection_kind = "repeated"
            mock_get.return_value = guard
            assert _loop_kind_from_exception(exc) == "repeated"

    def test_stuck_exception_guard_failure_returns_none(self) -> None:
        exc = type("ToolStuckException", (Exception,), {})("ToolStuckException")
        with patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.get_loop_guard",
            side_effect=RuntimeError("no guard"),
        ):
            assert _loop_kind_from_exception(exc) is None


class TestGetToolArgs:
    def test_missing_args_returns_empty(self) -> None:
        request = MagicMock()
        request.tool_call = {"name": "t", "id": "c"}
        assert _get_tool_args(request) == {}

    def test_non_dict_args_returns_empty(self) -> None:
        request = MagicMock()
        request.tool_call = {"name": "t", "args": "nope", "id": "c"}
        assert _get_tool_args(request) == {}

    def test_dict_args_returned(self) -> None:
        request = MagicMock()
        request.tool_call = {"name": "t", "args": {"a": 1}, "id": "c"}
        assert _get_tool_args(request) == {"a": 1}


@pytest.mark.asyncio
async def test_inner_success_path_with_token_logging() -> None:
    """Success path with positive token delta triggers event logger."""
    result = ToolMessage(content="ok", name="test_tool", tool_call_id="call_123")
    usage = MagicMock()
    usage.total_tokens = 100

    async def _mock_handler(_req: object) -> ToolMessage:
        usage.total_tokens = 150  # simulate token growth during execution
        return result

    pre_result = MagicMock()
    pre_result.blocked = False
    pre_result.loop_guard = MagicMock()
    pre_result.loop_verdict = MagicMock()
    pre_result.freq_guard = MagicMock()
    pre_result.freq_verdict = MagicMock()
    pre_result.steering_token = MagicMock()

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.run_pre_call_guards",
            return_value=pre_result,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.run_post_call_guards",
            return_value=result,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.get_token_tracker"
        ) as mock_tracker,
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.get_event_logger"
        ) as mock_logger,
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.emit_tool_heartbeat",
            return_value=asyncio.create_task(asyncio.sleep(0)),
        ),
        patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_allowed_domains_map",
            return_value={},
        ),
    ):
        tracker = MagicMock()
        tracker.tool_usage = {"test_tool": usage}
        mock_tracker.return_value = tracker

        logger_inst = AsyncMock()
        mock_logger.return_value = logger_inst

        res = await _tool_interceptor_middleware_inner(_request(), _mock_handler)
        assert res == result
        logger_inst.log.assert_awaited_once()
        assert logger_inst.log.call_args[0][0] == "tool_token_usage"
        assert logger_inst.log.call_args[0][1] == {
            "tool_name": "test_tool",
            "tokens": 50,
        }


@pytest.mark.asyncio
async def test_inner_clarification_approve_continue() -> None:
    """ToolClarificationError → interrupt returns approve → retry succeeds."""
    result = ToolMessage(content="ok", name="test_tool", tool_call_id="call_123")
    usage = MagicMock()
    usage.total_tokens = 0

    pre_result = MagicMock()
    pre_result.blocked = False
    pre_result.loop_guard = MagicMock()
    pre_result.loop_verdict = MagicMock()
    pre_result.freq_guard = MagicMock()
    pre_result.freq_verdict = MagicMock()
    pre_result.steering_token = MagicMock()

    mock_execute = AsyncMock(side_effect=[ToolClarificationError("clarify"), result])

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.run_pre_call_guards",
            return_value=pre_result,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.run_post_call_guards",
            return_value=result,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.execute_with_retry",
            mock_execute,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.get_token_tracker",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.emit_tool_heartbeat",
            return_value=asyncio.create_task(asyncio.sleep(0)),
        ),
        patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_allowed_domains_map",
            return_value={},
        ),
        patch("langgraph.types.interrupt", return_value={"type": "approve"}),
    ):
        res = await _tool_interceptor_middleware_inner(_request(), _noop_handler)
        assert res == result
        assert mock_execute.await_count == 2


@pytest.mark.asyncio
async def test_inner_clarification_edited_payload() -> None:
    """Approval with edited_payload rewrites request args and retries."""
    result = ToolMessage(content="ok", name="test_tool", tool_call_id="call_123")
    usage = MagicMock()
    usage.total_tokens = 0

    pre_result = MagicMock()
    pre_result.blocked = False
    pre_result.loop_guard = MagicMock()
    pre_result.loop_verdict = MagicMock()
    pre_result.freq_guard = MagicMock()
    pre_result.freq_verdict = MagicMock()
    pre_result.steering_token = MagicMock()

    mock_execute = AsyncMock(side_effect=[ToolClarificationError("clarify"), result])

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.run_pre_call_guards",
            return_value=pre_result,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.run_post_call_guards",
            return_value=result,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.execute_with_retry",
            mock_execute,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.get_token_tracker",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.emit_tool_heartbeat",
            return_value=asyncio.create_task(asyncio.sleep(0)),
        ),
        patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_allowed_domains_map",
            return_value={},
        ),
        patch(
            "langgraph.types.interrupt",
            return_value={"type": "approve", "edited_payload": {"fixed": True}},
        ),
    ):
        request = _request()
        res = await _tool_interceptor_middleware_inner(request, _noop_handler)
        assert res == result
        assert mock_execute.await_count == 2
        assert request.tool_call["args"] == {"fixed": True}


@pytest.mark.asyncio
async def test_inner_clarification_rejected_breaks() -> None:
    """Rejection breaks the loop; missing result routes to handle_execution_error."""
    usage = MagicMock()
    usage.total_tokens = 0

    pre_result = MagicMock()
    pre_result.blocked = False
    pre_result.loop_guard = MagicMock()
    pre_result.loop_verdict = MagicMock()
    pre_result.freq_guard = MagicMock()
    pre_result.freq_verdict = MagicMock()
    pre_result.steering_token = MagicMock()

    mock_execute = AsyncMock(side_effect=ToolClarificationError("clarify"))

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.run_pre_call_guards",
            return_value=pre_result,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.execute_with_retry",
            mock_execute,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.get_token_tracker",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.emit_tool_heartbeat",
            return_value=asyncio.create_task(asyncio.sleep(0)),
        ),
        patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_allowed_domains_map",
            return_value={},
        ),
        patch("langgraph.types.interrupt", return_value={"type": "reject"}),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.handle_execution_error"
        ) as mock_handle,
    ):
        mock_handle.return_value = ToolMessage(
            content="clarification_rejected", name="test_tool", tool_call_id="call_123"
        )
        res = await _tool_interceptor_middleware_inner(_request(), _noop_handler)
        assert "clarification_rejected" in res.content
        assert mock_execute.await_count == 1
        mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_inner_cancelled_error_handled() -> None:
    """asyncio.CancelledError routes to handle_cancellation."""
    usage = MagicMock()
    usage.total_tokens = 0

    async def _handler(_req: object) -> ToolMessage:
        raise asyncio.CancelledError("user cancelled")

    pre_result = MagicMock()
    pre_result.blocked = False
    pre_result.loop_guard = MagicMock()
    pre_result.loop_verdict = MagicMock()
    pre_result.freq_guard = MagicMock()
    pre_result.freq_verdict = MagicMock()
    pre_result.steering_token = MagicMock()

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.run_pre_call_guards",
            return_value=pre_result,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.get_token_tracker",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.emit_tool_heartbeat",
            return_value=asyncio.create_task(asyncio.sleep(0)),
        ),
        patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_allowed_domains_map",
            return_value={},
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.handle_cancellation"
        ) as mock_handle,
    ):
        mock_handle.return_value = ToolMessage(content="user_cancelled", name="test_tool", tool_call_id="call_123")
        res = await _tool_interceptor_middleware_inner(_request(), _handler)
        assert "user_cancelled" in res.content
        mock_handle.assert_called_once()


@patch("myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.logger")
def test_notify_compaction_logs_when_previous_calls(mock_logger: MagicMock) -> None:
    guard = MagicMock()
    guard._metrics.total_calls = 7
    with (
        patch("myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware._loop_guard_var") as mock_var,
    ):
        mock_var.get.return_value = guard
        notify_loop_guard_compaction()
    guard.notify_compaction.assert_called_once()
    mock_logger.debug.assert_called_once()
