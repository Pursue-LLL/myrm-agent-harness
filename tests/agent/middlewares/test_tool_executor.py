"""Tests for tool_executor module."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares.tooling.tool_executor import (
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
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_event_logger",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_terminal_errors",
            return_value=set(),
        ),
    ):
        yield


@pytest.mark.usefixtures("_no_event_logger")
class TestExecuteWithRetrySuccess:
    @pytest.mark.asyncio
    async def test_success_first_attempt(self) -> None:
        handler = AsyncMock(
            return_value=ToolMessage(content="ok", name="my_tool", tool_call_id="tc_1")
        )
        result = await execute_with_retry(
            _make_request(),
            handler,
            "my_tool",
            "tc_1",
            allowed_domains=None,
        )
        assert isinstance(result, ToolMessage)
        assert result.content == "ok"
        handler.assert_awaited_once()


@pytest.mark.usefixtures("_no_event_logger")
class TestExecuteWithRetryToolArgsTimeout:
    """execute_with_retry must forward tool args so an explicit timeout survives."""

    @pytest.mark.asyncio
    async def test_tool_args_timeout_reaches_get_tool_timeout(self) -> None:
        handler = AsyncMock(
            return_value=ToolMessage(
                content="ok", name="bash_code_execute_tool", tool_call_id="tc_1"
            )
        )
        request = _make_request("bash_code_execute_tool")
        request.tool_call = {
            "name": "bash_code_execute_tool",
            "id": "tc_1",
            "args": {"timeout": 300},
        }
        with patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_tool_timeout",
            return_value=300.0,
        ) as mock_timeout:
            await execute_with_retry(
                request,
                handler,
                "bash_code_execute_tool",
                "tc_1",
                allowed_domains=None,
            )
        mock_timeout.assert_called_once()
        assert mock_timeout.call_args.args == (
            "bash_code_execute_tool",
            {"timeout": 300},
        )

    @pytest.mark.asyncio
    async def test_forwards_explicit_tool_timeout_from_args(self) -> None:
        """bash 工具显式 timeout 必须透传给 get_tool_timeout 尊重长任务。"""
        req = MagicMock()
        req.tool_call = {
            "name": "bash_code_execute_tool",
            "id": "tc_1",
            "args": {"timeout": 240},
        }
        handler = AsyncMock(
            return_value=ToolMessage(
                content="ok", name="bash_code_execute_tool", tool_call_id="tc_1"
            )
        )
        with patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_tool_timeout",
            return_value=240.0,
        ) as mock_timeout:
            result = await execute_with_retry(
                req,
                handler,
                "bash_code_execute_tool",
                "tc_1",
                allowed_domains=None,
            )
        assert result.content == "ok"
        mock_timeout.assert_called_once_with("bash_code_execute_tool", {"timeout": 240})


@pytest.mark.usefixtures("_no_event_logger")
class TestExecuteWithRetryTimeout:
    @pytest.mark.asyncio
    async def test_timeout_retries_then_raises(self) -> None:
        async def slow_handler(req: MagicMock) -> ToolMessage:
            await asyncio.sleep(999)
            return ToolMessage(content="never", name="t", tool_call_id="id")

        with (
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_tool_timeout",
                return_value=0.01,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor._emit_timeout_event",
                new_callable=AsyncMock,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor._emit_retry_event",
                new_callable=AsyncMock,
            ),
        ):
            with pytest.raises(ToolError) as exc_info:
                await execute_with_retry(
                    _make_request(),
                    slow_handler,
                    "slow_tool",
                    "tc_1",
                    allowed_domains=None,
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
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_tool_timeout",
                return_value=0.01,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor._emit_timeout_event",
                new_callable=AsyncMock,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor._emit_retry_event",
                new_callable=AsyncMock,
            ),
        ):
            result = await execute_with_retry(
                _make_request(),
                intermittent_handler,
                "t",
                "tc_1",
                allowed_domains=None,
            )
            assert result.content == "ok"
            assert call_count == 2


@pytest.mark.usefixtures("_no_event_logger")
class TestExecuteWithRetryMetrics:
    @pytest.mark.asyncio
    async def test_timeout_records_failure_metric(self) -> None:
        """Timeout final failure increments the failed counter with error_type=timeout."""
        failed = MagicMock()

        async def slow_handler(req: MagicMock) -> ToolMessage:
            await asyncio.sleep(999)
            return ToolMessage(content="never", name="t", tool_call_id="id")

        with (
            patch(
                "myrm_agent_harness.observability.metrics.agent_metrics.tool_execution_failed_total",
                failed,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_tool_timeout",
                return_value=0.01,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor._emit_timeout_event",
                new_callable=AsyncMock,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor._emit_retry_event",
                new_callable=AsyncMock,
            ),
        ):
            with pytest.raises(ToolError) as exc_info:
                await execute_with_retry(
                    _make_request(),
                    slow_handler,
                    "slow_tool",
                    "tc_1",
                    allowed_domains=None,
                )
            assert exc_info.value.error_code == "TIMEOUT_MAX_RETRIES"
            failed.labels.assert_called_once_with(tool_name="slow_tool", error_type="timeout")

    @pytest.mark.asyncio
    async def test_tool_error_metric_and_terminal_register(self) -> None:
        """A network_blocked ToolError increments the counter and registers the terminal category."""
        failed = MagicMock()
        terminal_errors: set[str] = set()

        def handler(req: MagicMock) -> ToolMessage:
            raise ToolError(
                message="blocked",
                diagnostic_info={"error_category": "network_blocked"},
                user_hint="network blocked for security",
            )

        with patch(
            "myrm_agent_harness.observability.metrics.agent_metrics.tool_execution_failed_total",
            failed,
        ), patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_terminal_errors",
            return_value=terminal_errors,
        ):
            result = await execute_with_retry(
                _make_request(),
                handler,
                "my_tool",
                "tc_1",
                allowed_domains=None,
            )
        assert "blocked" in result.content
        assert "network_blocked" in terminal_errors
        failed.labels.assert_called_once_with(tool_name="my_tool", error_type="network_blocked")


@pytest.mark.usefixtures("_no_event_logger")
class TestExecuteWithRetryErrors:
    @pytest.mark.asyncio
    async def test_non_retryable_tool_error_returns_error_msg(self) -> None:
        err = ToolError(
            message="sandbox blocked",
            user_hint="check network",
            diagnostic_info={"error_category": "network_blocked"},
        )
        handler = AsyncMock(side_effect=err)
        result = await execute_with_retry(
            _make_request(),
            handler,
            "my_tool",
            "tc_1",
            allowed_domains=None,
        )
        assert isinstance(result, ToolMessage)
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_non_retryable_raises_directly(self) -> None:
        from myrm_agent_harness.toolkits.browser.exceptions import BrowserError

        handler = AsyncMock(side_effect=BrowserError("browser crash"))
        with pytest.raises(BrowserError):
            await execute_with_retry(
                _make_request(),
                handler,
                "browser_tool",
                "tc_1",
                allowed_domains=None,
            )

    @pytest.mark.asyncio
    async def test_retryable_error_retries_then_raises(self) -> None:
        handler = AsyncMock(side_effect=RuntimeError("transient"))
        with (
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            with pytest.raises(ToolError) as exc_info:
                await execute_with_retry(
                    _make_request(),
                    handler,
                    "search_tool",
                    "tc_1",
                    allowed_domains=None,
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
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await execute_with_retry(
                _make_request(),
                intermittent_handler,
                "search_tool",
                "tc_1",
                allowed_domains=None,
            )
            assert result.content == "ok"
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_retryable_error_honors_retry_after_header(self) -> None:
        """A response Retry-After header is parsed and used as backoff."""
        call_count = 0

        async def rate_limited(req: MagicMock) -> ToolMessage:
            nonlocal call_count
            call_count += 1
            e = RuntimeError("rate limited")
            resp = MagicMock()
            resp.headers = {"Retry-After": "1.5"}
            e.response = resp  # type: ignore[attr-defined]
            raise e

        with (
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            with pytest.raises(ToolError) as exc_info:
                await execute_with_retry(
                    _make_request(tool_name="search_tool"),
                    rate_limited,
                    "search_tool",
                    "tc_1",
                    allowed_domains=None,
                )
            assert exc_info.value.error_code == "MAX_RETRIES_EXCEEDED"
            assert call_count == 2
            assert mock_sleep.await_count >= 1

    @pytest.mark.asyncio
    async def test_graph_interrupt_propagates(self) -> None:
        from langgraph.errors import GraphInterrupt

        handler = AsyncMock(side_effect=GraphInterrupt())
        with pytest.raises(GraphInterrupt):
            await execute_with_retry(
                _make_request(),
                handler,
                "my_tool",
                "tc_1",
                allowed_domains=None,
            )

    @pytest.mark.asyncio
    async def test_timeout_with_event_logger(self) -> None:
        """Verify event_logger.log is called on timeout/retry when available."""
        event_logger = AsyncMock()

        async def slow(req: MagicMock) -> ToolMessage:
            await asyncio.sleep(999)
            return ToolMessage(content="x", name="t", tool_call_id="id")

        with (
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_event_logger",
                return_value=event_logger,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_terminal_errors",
                return_value=set(),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_tool_timeout",
                return_value=0.01,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor._emit_timeout_event",
                new_callable=AsyncMock,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor._emit_retry_event",
                new_callable=AsyncMock,
            ),
            pytest.raises(ToolError),
        ):
            await execute_with_retry(
                _make_request(), slow, "t", "tc_1", allowed_domains=None
            )
        assert event_logger.log.await_count >= 2

    @pytest.mark.asyncio
    async def test_retryable_error_with_event_logger(self) -> None:
        """Verify event_logger.log is called on retryable error."""
        event_logger = AsyncMock()
        handler = AsyncMock(side_effect=RuntimeError("transient"))
        with (
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_event_logger",
                return_value=event_logger,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_terminal_errors",
                return_value=set(),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_executor.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(ToolError),
        ):
            await execute_with_retry(
                _make_request(), handler, "search", "tc_1", allowed_domains=None
            )
        assert event_logger.log.await_count >= 1

    @pytest.mark.asyncio
    async def test_tool_error_with_terminal_category_registers(self) -> None:
        terminal_errors: set[str] = set()
        err = ToolError(
            message="blocked",
            diagnostic_info={"error_category": "sandbox_ro"},
        )
        handler = AsyncMock(side_effect=err)
        with patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_terminal_errors",
            return_value=terminal_errors,
        ):
            result = await execute_with_retry(
                _make_request(),
                handler,
                "file_tool",
                "tc_1",
                allowed_domains=None,
            )
            assert isinstance(result, ToolMessage)
            assert "sandbox_ro" in terminal_errors

    @pytest.mark.asyncio
    async def test_bash_guardrail_tool_error_propagates_category(self) -> None:
        err = ToolError(
            message="Command blocked: import myrm_tools",
            user_hint="Use skills.* imports instead.",
            diagnostic_info={"error_category": "guardrail_blocked"},
            error_code="MYRM_TOOLS_BLOCKED",
        )
        handler = AsyncMock(side_effect=err)
        result = await execute_with_retry(
            _make_request("bash_code_execute_tool"),
            handler,
            "bash_code_execute_tool",
            "tc_1",
            allowed_domains=None,
        )
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert result.additional_kwargs.get("error_category") == "guardrail_blocked"
        assert (
            result.additional_kwargs.get("error_hint")
            == "Use skills.* imports instead."
        )

    @pytest.mark.asyncio
    async def test_emit_timeout_event_with_sink(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling.tool_executor import (
            _emit_timeout_event,
        )

        sink = AsyncMock()
        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            return_value=sink,
        ):
            await _emit_timeout_event("my_tool", 60.0, 0, 500.0)
        sink.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_emit_timeout_event_no_sink(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling.tool_executor import (
            _emit_timeout_event,
        )

        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            return_value=None,
        ):
            await _emit_timeout_event("my_tool", 60.0, 0, 500.0)

    @pytest.mark.asyncio
    async def test_emit_timeout_event_exception_handled(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling.tool_executor import (
            _emit_timeout_event,
        )

        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            side_effect=RuntimeError("broken"),
        ):
            await _emit_timeout_event("my_tool", 60.0, 0, 500.0)

    @pytest.mark.asyncio
    async def test_emit_retry_event_with_sink(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling.tool_executor import (
            _emit_retry_event,
        )

        sink = AsyncMock()
        with (
            patch(
                "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
                return_value=sink,
            ),
            patch(
                "myrm_agent_harness.toolkits.code_execution.executors.models.scrub_sensitive_info",
                side_effect=lambda x: x,
            ),
        ):
            await _emit_retry_event("my_tool", 0, 1.5)
        sink.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_emit_retry_event_no_sink(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling.tool_executor import (
            _emit_retry_event,
        )

        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            return_value=None,
        ):
            await _emit_retry_event("my_tool", 0, 1.5)

    @pytest.mark.asyncio
    async def test_emit_retry_event_exception_handled(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling.tool_executor import (
            _emit_retry_event,
        )

        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            side_effect=RuntimeError("broken"),
        ):
            await _emit_retry_event("my_tool", 0, 1.5)
