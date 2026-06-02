"""Tests for safety_dispatcher middleware — tool concurrency safety control."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.middlewares.safety_dispatcher import (
    create_safety_dispatcher,
)


def _make_request(tool_name: str) -> object:
    """Create a minimal ToolCallRequest-like object for testing."""

    class FakeRequest:
        def __init__(self, name: str) -> None:
            self.tool_call: dict[str, str] = {"name": name, "id": "fake_id"}
            self.state = {}

    return FakeRequest(tool_name)


async def _invoke_middleware(
    middleware: object, request: object, handler: Callable[..., Awaitable[object]]
) -> object:
    """Invoke the middleware's awrap_tool_call hook directly."""
    return await middleware.awrap_tool_call(request, handler)  # type: ignore[attr-defined]


class TestSafetyDispatcher:
    @pytest.mark.asyncio
    async def test_safe_tool_executes_without_lock(self) -> None:
        middleware = create_safety_dispatcher()
        handler = AsyncMock(return_value="ok")
        request = _make_request("file_read_tool")

        result = await _invoke_middleware(middleware, request, handler)

        assert result == "ok"
        handler.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_unsafe_tool_executes_with_serialization(self) -> None:
        middleware = create_safety_dispatcher()
        handler = AsyncMock(return_value="ok")
        request = _make_request("bash_code_execute_tool")

        result = await _invoke_middleware(middleware, request, handler)

        assert result == "ok"
        handler.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_unknown_tool_uses_fail_closed(self) -> None:
        middleware = create_safety_dispatcher()
        handler = AsyncMock(return_value="ok")
        request = _make_request("unknown_mcp_tool")

        result = await _invoke_middleware(middleware, request, handler)

        assert result == "ok"
        handler.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_empty_name_uses_fail_closed(self) -> None:
        middleware = create_safety_dispatcher()
        handler = AsyncMock(return_value="ok")
        request = _make_request("")

        result = await _invoke_middleware(middleware, request, handler)

        assert result == "ok"
        handler.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_unsafe_tools_serialize_not_interleave(self) -> None:
        """Two unsafe tools via the same dispatcher must not overlap execution."""
        middleware = create_safety_dispatcher()
        execution_log: list[str] = []

        async def slow_handler(req: object) -> str:
            name = req.tool_call["name"]  # type: ignore[attr-defined]
            execution_log.append(f"{name}:start")
            await asyncio.sleep(0.05)
            execution_log.append(f"{name}:end")
            return f"{name}:done"

        r1 = _make_request("bash_code_execute_tool")
        r2 = _make_request("file_write_tool")

        await asyncio.gather(
            _invoke_middleware(middleware, r1, slow_handler),
            _invoke_middleware(middleware, r2, slow_handler),
        )

        assert len(execution_log) == 4
        assert execution_log[0].endswith(":start")
        assert execution_log[1].endswith(":end")

    @pytest.mark.asyncio
    async def test_safe_tools_can_run_concurrently(self) -> None:
        """Two safe tools should execute concurrently (no Lock)."""
        middleware = create_safety_dispatcher()
        execution_log: list[str] = []

        async def slow_handler(req: object) -> str:
            name = req.tool_call["name"]  # type: ignore[attr-defined]
            execution_log.append(f"{name}:start")
            await asyncio.sleep(0.05)
            execution_log.append(f"{name}:end")
            return f"{name}:done"

        r1 = _make_request("file_read_tool")
        r2 = _make_request("grep_tool")

        await asyncio.gather(
            _invoke_middleware(middleware, r1, slow_handler),
            _invoke_middleware(middleware, r2, slow_handler),
        )

        starts = [e for e in execution_log if e.endswith(":start")]
        assert len(starts) == 2
        assert execution_log[0].endswith(":start")
        assert execution_log[1].endswith(":start")

    @pytest.mark.asyncio
    async def test_handler_exception_releases_lock(self) -> None:
        middleware = create_safety_dispatcher()

        async def failing_handler(req: object) -> str:
            raise ValueError("tool failed")

        request = _make_request("bash_code_execute_tool")

        with pytest.raises(ValueError, match="tool failed"):
            await _invoke_middleware(middleware, request, failing_handler)

        ok_handler = AsyncMock(return_value="recovered")
        result = await _invoke_middleware(middleware, request, ok_handler)
        assert result == "recovered"

    @pytest.mark.asyncio
    async def test_separate_dispatchers_have_independent_locks(self) -> None:
        m1 = create_safety_dispatcher()
        m2 = create_safety_dispatcher()

        execution_log: list[str] = []

        async def slow_handler(req: object) -> str:
            name = req.tool_call["name"]  # type: ignore[attr-defined]
            execution_log.append(f"{name}:start")
            await asyncio.sleep(0.05)
            execution_log.append(f"{name}:end")
            return f"{name}:done"

        r = _make_request("bash_code_execute_tool")

        await asyncio.gather(
            _invoke_middleware(m1, r, slow_handler),
            _invoke_middleware(m2, r, slow_handler),
        )

        starts = [e for e in execution_log if e.endswith(":start")]
        assert len(starts) == 2
        assert execution_log[0].endswith(":start")
        assert execution_log[1].endswith(":start")

    @pytest.mark.asyncio
    async def test_mid_batch_failure_skips_subsequent_tools(self) -> None:
        """If an unsafe tool fails, subsequent unsafe tools in the same batch should be skipped."""
        from langchain_core.messages import AIMessage, ToolMessage

        middleware = create_safety_dispatcher()
        execution_log: list[str] = []

        # Create a shared state with an AIMessage to simulate a batch
        msg = AIMessage(
            content="",
            tool_calls=[
                {"name": "bash_code_execute_tool", "args": {}, "id": "call_1"},
                {"name": "file_write_tool", "args": {}, "id": "call_2"},
            ],
        )
        shared_state = {"messages": [msg]}

        class BatchFakeRequest:
            def __init__(self, name: str, call_id: str) -> None:
                self.tool_call: dict[str, str] = {"name": name, "id": call_id}
                self.state = shared_state

        r1 = BatchFakeRequest("bash_code_execute_tool", "call_1")
        r2 = BatchFakeRequest("file_write_tool", "call_2")

        async def failing_handler(req: object) -> ToolMessage:
            name = req.tool_call["name"]  # type: ignore[attr-defined]
            execution_log.append(f"{name}:start")
            await asyncio.sleep(0.05)
            if name == "bash_code_execute_tool":
                execution_log.append(f"{name}:fail")
                return ToolMessage(content="error", name=name, tool_call_id=req.tool_call["id"], status="error")  # type: ignore[attr-defined]
            execution_log.append(f"{name}:end")
            return ToolMessage(content="ok", name=name, tool_call_id=req.tool_call["id"], status="success")  # type: ignore[attr-defined]

        results = await asyncio.gather(
            _invoke_middleware(middleware, r1, failing_handler),
            _invoke_middleware(middleware, r2, failing_handler),
        )

        # Only the first tool should have started
        assert "bash_code_execute_tool:start" in execution_log
        assert "bash_code_execute_tool:fail" in execution_log
        assert "file_write_tool:start" not in execution_log

        # The second tool should return a skipped error message
        assert isinstance(results[1], ToolMessage)
        assert results[1].status == "error"
        assert "[SKIPPED]" in str(results[1].content)
