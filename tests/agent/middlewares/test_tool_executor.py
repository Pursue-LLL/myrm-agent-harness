"""Tests for tool_executor module."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares.tool_executor import (
    execute_with_retry,
)
from myrm_agent_harness.utils.errors import ToolError


def _make_request(tool_name: str = "my_tool", tool_call_id: str = "tc_1") -> MagicMock:
    req = MagicMock()
    req.tool_call = {"name": tool_name, "id": tool_call_id}
    return req


@pytest.fixture()
def _no_event_logger() -> Any:
    """Patch session context to return no event logger and empty terminal errors."""
    with (
        patch("myrm_agent_harness.agent.middlewares.tool_executor.get_event_logger", return_value=None),
        patch("myrm_agent_harness.agent.middlewares.tool_executor.get_terminal_errors", return_value=set()),
    ):
        yield


@pytest.mark.usefixtures("_no_event_logger")
class TestExecuteWithRetrySuccess:
    @pytest.mark.asyncio
    async def test_success_first_attempt(self) -> None:
        handler = AsyncMock(return_value=ToolMessage(content="ok", name="my_tool", tool_call_id="tc_1"))
        result = await execute_with_retry(
            _make_request(), handler, "my_tool", "tc_1", allowed_domains=None,
        )
        assert isinstance(result, ToolMessage)
        assert result.content == "ok"
        handler.assert_awaited_once()


@pytest.mark.usefixtures("_no_event_logger")
class TestExecuteWithRetryTimeout:
    @pytest.mark.asyncio
    async def test_timeout_retries_then_raises(self) -> None:
        async def slow_handler(req: MagicMock) -> ToolMessage:
            await asyncio.sleep(999)
            return ToolMessage(content="never", name="t", tool_call_id="id")

        with (
            patch("myrm_agent_harness.agent.middlewares.tool_executor.get_tool_timeout", return_value=0.01),
            patch("myrm_agent_harness.agent.middlewares.tool_executor._emit_timeout_event", new_callable=AsyncMock),
            patch("myrm_agent_harness.agent.middlewares.tool_executor._emit_retry_event", new_callable=AsyncMock),
        ):
            with pytest.raises(ToolError) as exc_info:
                await execute_with_retry(
                    _make_request(), slow_handler, "slow_tool", "tc_1", allowed_domains=None,
                )
            assert exc_info.value.error_code == "TIMEOUT_MAX_RETRIES"
            assert "timed out" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_timeout_first_then_success(self) -> None:
        call_count = 0

        async def intermittent_handler(req: MagicMock) -> ToolMessage:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(999)
            return ToolMessage(content="ok", name="t", tool_call_id="id")

        with (
            patch("myrm_agent_harness.agent.middlewares.tool_executor.get_tool_timeout", return_value=0.01),
            patch("myrm_agent_harness.agent.middlewares.tool_executor._emit_timeout_event", new_callable=AsyncMock),
            patch("myrm_agent_harness.agent.middlewares.tool_executor._emit_retry_event", new_callable=AsyncMock),
        ):
            result = await execute_with_retry(
                _make_request(), intermittent_handler, "t", "tc_1", allowed_domains=None,
            )
            assert result.content == "ok"
            assert call_count == 2


@pytest.mark.usefixtures("_no_event_logger")
class TestExecuteWithRetryErrors:
    @pytest.mark.asyncio
    async def test_non_retryable_tool_error_returns_error_msg(self) -> None:
        err = ToolError(message="sandbox blocked", user_hint="check network")
        err.error_category = "network_blocked"  # type: ignore[attr-defined]
        handler = AsyncMock(side_effect=err)
        result = await execute_with_retry(
            _make_request(), handler, "my_tool", "tc_1", allowed_domains=None,
        )
        assert isinstance(result, ToolMessage)
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_non_retryable_raises_directly(self) -> None:
        from myrm_agent_harness.toolkits.browser.exceptions import BrowserError

        handler = AsyncMock(side_effect=BrowserError("browser crash"))
        with pytest.raises(BrowserError):
            await execute_with_retry(
                _make_request(), handler, "browser_tool", "tc_1", allowed_domains=None,
            )

    @pytest.mark.asyncio
    async def test_retryable_error_retries_then_raises(self) -> None:
        handler = AsyncMock(side_effect=RuntimeError("transient"))
        with (
            patch("myrm_agent_harness.agent.middlewares.tool_executor.asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(ToolError) as exc_info:
                await execute_with_retry(
                    _make_request(), handler, "search_tool", "tc_1", allowed_domains=None,
                )
            assert exc_info.value.error_code == "MAX_RETRIES_EXCEEDED"
            assert handler.await_count == 2

    @pytest.mark.asyncio
    async def test_retryable_error_succeeds_on_retry(self) -> None:
        call_count = 0

        async def intermittent_handler(req: MagicMock) -> ToolMessage:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient failure")
            return ToolMessage(content="ok", name="t", tool_call_id="id")

        with (
            patch("myrm_agent_harness.agent.middlewares.tool_executor.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await execute_with_retry(
                _make_request(), intermittent_handler, "search_tool", "tc_1", allowed_domains=None,
            )
            assert result.content == "ok"
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_graph_interrupt_propagates(self) -> None:
        from langgraph.errors import GraphInterrupt

        handler = AsyncMock(side_effect=GraphInterrupt())
        with pytest.raises(GraphInterrupt):
            await execute_with_retry(
                _make_request(), handler, "my_tool", "tc_1", allowed_domains=None,
            )

    @pytest.mark.asyncio
    async def test_timeout_with_event_logger(self) -> None:
        """Verify event_logger.log is called on timeout/retry when available."""
        event_logger = AsyncMock()
        async def slow(req: MagicMock) -> ToolMessage:
            await asyncio.sleep(999)
            return ToolMessage(content="x", name="t", tool_call_id="id")

        with (
            patch("myrm_agent_harness.agent.middlewares.tool_executor.get_event_logger", return_value=event_logger),
            patch("myrm_agent_harness.agent.middlewares.tool_executor.get_terminal_errors", return_value=set()),
            patch("myrm_agent_harness.agent.middlewares.tool_executor.get_tool_timeout", return_value=0.01),
            patch("myrm_agent_harness.agent.middlewares.tool_executor._emit_timeout_event", new_callable=AsyncMock),
            patch("myrm_agent_harness.agent.middlewares.tool_executor._emit_retry_event", new_callable=AsyncMock),
        ):
            with pytest.raises(ToolError):
                await execute_with_retry(_make_request(), slow, "t", "tc_1", allowed_domains=None)
        assert event_logger.log.await_count >= 2

    @pytest.mark.asyncio
    async def test_retryable_error_with_event_logger(self) -> None:
        """Verify event_logger.log is called on retryable error."""
        event_logger = AsyncMock()
        handler = AsyncMock(side_effect=RuntimeError("transient"))
        with (
            patch("myrm_agent_harness.agent.middlewares.tool_executor.get_event_logger", return_value=event_logger),
            patch("myrm_agent_harness.agent.middlewares.tool_executor.get_terminal_errors", return_value=set()),
            patch("myrm_agent_harness.agent.middlewares.tool_executor.asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(ToolError):
                await execute_with_retry(_make_request(), handler, "search", "tc_1", allowed_domains=None)
        assert event_logger.log.await_count >= 1

    @pytest.mark.asyncio
    async def test_tool_error_with_terminal_category_registers(self) -> None:
        terminal_errors: set[str] = set()
        err = ToolError(message="blocked")
        err.error_category = "sandbox_ro"  # type: ignore[attr-defined]
        handler = AsyncMock(side_effect=err)
        with patch(
            "myrm_agent_harness.agent.middlewares.tool_executor.get_terminal_errors",
            return_value=terminal_errors,
        ):
            result = await execute_with_retry(
                _make_request(), handler, "file_tool", "tc_1", allowed_domains=None,
            )
            assert isinstance(result, ToolMessage)
            assert "sandbox_ro" in terminal_errors


class TestEmitEvents:
    @pytest.mark.asyncio
    async def test_emit_timeout_event_with_sink(self) -> None:
        from myrm_agent_harness.agent.middlewares.tool_executor import _emit_timeout_event

        sink = AsyncMock()
        with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=sink):
            await _emit_timeout_event("my_tool", 60.0, 0, 500.0)
        sink.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_emit_timeout_event_no_sink(self) -> None:
        from myrm_agent_harness.agent.middlewares.tool_executor import _emit_timeout_event

        with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=None):
            await _emit_timeout_event("my_tool", 60.0, 0, 500.0)

    @pytest.mark.asyncio
    async def test_emit_timeout_event_exception_handled(self) -> None:
        from myrm_agent_harness.agent.middlewares.tool_executor import _emit_timeout_event

        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            side_effect=RuntimeError("broken"),
        ):
            await _emit_timeout_event("my_tool", 60.0, 0, 500.0)

    @pytest.mark.asyncio
    async def test_emit_retry_event_with_sink(self) -> None:
        from myrm_agent_harness.agent.middlewares.tool_executor import _emit_retry_event

        sink = AsyncMock()
        with (
            patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=sink),
            patch(
                "myrm_agent_harness.toolkits.code_execution.executors.models.scrub_sensitive_info",
                side_effect=lambda x: x,
            ),
        ):
            await _emit_retry_event("my_tool", 0, 1.5)
        sink.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_emit_retry_event_no_sink(self) -> None:
        from myrm_agent_harness.agent.middlewares.tool_executor import _emit_retry_event

        with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=None):
            await _emit_retry_event("my_tool", 0, 1.5)

    @pytest.mark.asyncio
    async def test_emit_retry_event_exception_handled(self) -> None:
        from myrm_agent_harness.agent.middlewares.tool_executor import _emit_retry_event

        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            side_effect=RuntimeError("broken"),
        ):
            await _emit_retry_event("my_tool", 0, 1.5)
