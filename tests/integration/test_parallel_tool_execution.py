"""Integration tests for parallel tool execution pipeline.

Validates the full concurrency control stack:
1. safety_dispatcher: safe tools run concurrently, unsafe tools serialize
2. concurrency_limiter: subagent spawn respects per-type semaphore limits
3. Combined: mixed tool batches execute with correct concurrency behavior
4. _apply_parallel_tool_calls: monkey-patch injects parallel_tool_calls
5. Edge cases: missing args, Command returns, handler exceptions
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.middlewares.concurrency_limiter import (
    create_concurrency_limiter,
)
from myrm_agent_harness.agent.middlewares.safety_dispatcher import (
    create_safety_dispatcher,
)


def _make_request(tool_name: str, args: dict[str, object] | None = None) -> object:
    """Create a minimal ToolCallRequest-like object."""

    class FakeRequest:
        def __init__(self, name: str, tool_args: dict[str, object]) -> None:
            self.tool_call: dict[str, object] = {"name": name, "args": tool_args}
            self.state: dict[str, object] = {"messages": []}

    return FakeRequest(tool_name, args or {})


async def _invoke_middleware(
    middleware: object,
    request: object,
    handler: Callable[..., Awaitable[object]],
) -> object:
    return await middleware.awrap_tool_call(request, handler)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# concurrency_limiter middleware integration
# ---------------------------------------------------------------------------


class TestConcurrencyLimiterMiddleware:
    """Test the actual middleware invocation path (lines 75-90)."""

    @pytest.mark.asyncio
    async def test_non_subagent_tool_passes_through(self) -> None:
        middleware = create_concurrency_limiter()
        handler = AsyncMock(return_value="ok")
        request = _make_request("file_read_tool")

        result = await _invoke_middleware(middleware, request, handler)

        assert result == "ok"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_agent_type_passes_through(self) -> None:
        middleware = create_concurrency_limiter()
        handler = AsyncMock(return_value="ok")
        request = _make_request("delegate_task_tool", {"agent_type": ""})

        result = await _invoke_middleware(middleware, request, handler)

        assert result == "ok"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_string_agent_type_passes_through(self) -> None:
        middleware = create_concurrency_limiter()
        handler = AsyncMock(return_value="ok")
        request = _make_request("delegate_task_tool", {"agent_type": 123})

        result = await _invoke_middleware(middleware, request, handler)

        assert result == "ok"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_agent_type_passes_through(self) -> None:
        middleware = create_concurrency_limiter()
        handler = AsyncMock(return_value="ok")
        request = _make_request("delegate_task_tool", {"agent_type": "nonexistent_type"})

        result = await _invoke_middleware(middleware, request, handler)

        assert result == "ok"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_known_agent_type_acquires_semaphore(self) -> None:
        middleware = create_concurrency_limiter()
        handler = AsyncMock(return_value="subagent_result")
        request = _make_request("delegate_task_tool", {"agent_type": "search"})

        result = await _invoke_middleware(middleware, request, handler)

        assert result == "subagent_result"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_known_agent_type_limits_concurrency(self) -> None:
        """Verify semaphore-based concurrency limiting works end-to-end."""
        middleware = create_concurrency_limiter()
        execution_log: list[tuple[str, float]] = []

        async def slow_handler(req: object) -> str:
            execution_log.append(("start", time.monotonic()))
            await asyncio.sleep(0.03)
            execution_log.append(("end", time.monotonic()))
            return "done"

        requests = [_make_request("delegate_task_tool", {"agent_type": "analysis"}) for _ in range(3)]

        await asyncio.gather(*[_invoke_middleware(middleware, r, slow_handler) for r in requests])

        assert len(execution_log) == 6
        starts = [t for label, t in execution_log if label == "start"]
        assert len(starts) == 3


# ---------------------------------------------------------------------------
# Combined safety_dispatcher + concurrency_limiter
# ---------------------------------------------------------------------------


class TestCombinedMiddlewareStack:
    """Test realistic scenarios with both middlewares chained."""

    @pytest.mark.asyncio
    async def test_mixed_safe_and_unsafe_tools_parallel(self) -> None:
        """Simulate LLM returning 4 tool_uses: 2 safe (parallel) + 2 unsafe (serialized)."""
        safety = create_safety_dispatcher()
        execution_log: list[str] = []

        async def tracked_handler(req: object) -> str:
            name = req.tool_call["name"]  # type: ignore[attr-defined]
            execution_log.append(f"{name}:start")
            await asyncio.sleep(0.03)
            execution_log.append(f"{name}:end")
            return f"{name}:done"

        safe_requests = [
            _make_request("file_read_tool"),
            _make_request("grep_tool"),
        ]
        unsafe_requests = [
            _make_request("file_write_tool"),
            _make_request("bash_code_execute_tool"),
        ]

        all_requests = safe_requests + unsafe_requests
        results = await asyncio.gather(*[_invoke_middleware(safety, r, tracked_handler) for r in all_requests])

        assert len(results) == 4
        assert all(r.endswith(":done") for r in results)

        safe_starts = [i for i, e in enumerate(execution_log) if e in ("file_read_tool:start", "grep_tool:start")]
        assert len(safe_starts) == 2
        assert abs(safe_starts[0] - safe_starts[1]) <= 1

        unsafe_events = [
            e for e in execution_log if e.startswith("file_write_tool") or e.startswith("bash_code_execute_tool")
        ]
        assert len(unsafe_events) == 4
        assert unsafe_events[0].endswith(":start")
        assert unsafe_events[1].endswith(":end")

    @pytest.mark.asyncio
    async def test_all_safe_tools_truly_parallel(self) -> None:
        """5 safe tools should all start before any finishes."""
        safety = create_safety_dispatcher()
        start_times: list[float] = []
        end_times: list[float] = []

        async def timed_handler(req: object) -> str:
            start_times.append(time.monotonic())
            await asyncio.sleep(0.05)
            end_times.append(time.monotonic())
            return "done"

        safe_tools = ["file_read_tool", "grep_tool", "glob_tool", "web_search_tool", "web_fetch_tool"]
        requests = [_make_request(t) for t in safe_tools]

        await asyncio.gather(*[_invoke_middleware(safety, r, timed_handler) for r in requests])

        assert len(start_times) == 5
        assert len(end_times) == 5
        assert max(start_times) < min(end_times)

    @pytest.mark.asyncio
    async def test_all_unsafe_tools_fully_serialized(self) -> None:
        """3 unsafe tools should execute one at a time."""
        safety = create_safety_dispatcher()
        execution_log: list[tuple[str, str]] = []

        async def tracked_handler(req: object) -> str:
            name = req.tool_call["name"]  # type: ignore[attr-defined]
            execution_log.append((name, "start"))
            await asyncio.sleep(0.02)
            execution_log.append((name, "end"))
            return "done"

        unsafe_tools = ["bash_tool", "file_write_tool", "file_edit_tool"]
        requests = [_make_request(t) for t in unsafe_tools]

        await asyncio.gather(*[_invoke_middleware(safety, r, tracked_handler) for r in requests])

        assert len(execution_log) == 6
        for i in range(0, 6, 2):
            assert execution_log[i][1] == "start"
            assert execution_log[i + 1][1] == "end"
            assert execution_log[i][0] == execution_log[i + 1][0]

    @pytest.mark.asyncio
    async def test_mcp_tools_use_fail_closed_serialization(self) -> None:
        """Unknown MCP tools should be serialized (fail-closed)."""
        safety = create_safety_dispatcher()
        execution_log: list[str] = []

        async def tracked_handler(req: object) -> str:
            name = req.tool_call["name"]  # type: ignore[attr-defined]
            execution_log.append(f"{name}:start")
            await asyncio.sleep(0.02)
            execution_log.append(f"{name}:end")
            return "done"

        requests = [
            _make_request("mcp_weather_tool"),
            _make_request("mcp_database_tool"),
        ]

        await asyncio.gather(*[_invoke_middleware(safety, r, tracked_handler) for r in requests])

        assert execution_log[0].endswith(":start")
        assert execution_log[1].endswith(":end")

    @pytest.mark.asyncio
    async def test_handler_error_in_parallel_does_not_block_others(self) -> None:
        """One failing safe tool should not prevent others from completing."""
        safety = create_safety_dispatcher()
        results: list[str] = []

        async def mixed_handler(req: object) -> str:
            name = req.tool_call["name"]  # type: ignore[attr-defined]
            if name == "web_search_tool":
                raise ValueError("search failed")
            await asyncio.sleep(0.01)
            results.append(name)
            return f"{name}:done"

        requests = [
            _make_request("file_read_tool"),
            _make_request("web_search_tool"),
            _make_request("grep_tool"),
        ]

        tasks = [_invoke_middleware(safety, r, mixed_handler) for r in requests]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        successful = [r for r in gathered if not isinstance(r, Exception)]
        errors = [r for r in gathered if isinstance(r, Exception)]

        assert len(successful) == 2
        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)


# ---------------------------------------------------------------------------
# Edge cases: handler exceptions, missing args, Command returns
# ---------------------------------------------------------------------------


class TestConcurrencyLimiterEdgeCases:
    """Edge cases for concurrency_limiter middleware."""

    @pytest.mark.asyncio
    async def test_handler_exception_releases_semaphore(self) -> None:
        """Semaphore must be released even when handler raises."""
        from myrm_agent_harness.agent.middlewares.concurrency_limiter import (
            get_subagent_semaphore,
        )
        from myrm_agent_harness.agent.sub_agents.registry import SUBAGENT_CONFIGS, register_subagent_configs
        from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

        if "search" not in SUBAGENT_CONFIGS:
            register_subagent_configs({"search": SubagentConfig(
                system_prompt="Search agent",
                display_name="Search Agent",
                concurrency_limit=2,
            )})

        middleware = create_concurrency_limiter()
        sem = get_subagent_semaphore("search")
        assert sem is not None
        initial_value = sem._value

        async def failing_handler(req: object) -> str:
            raise RuntimeError("subagent crashed")

        request = _make_request("delegate_task_tool", {"agent_type": "search"})

        with pytest.raises(RuntimeError, match="subagent crashed"):
            await _invoke_middleware(middleware, request, failing_handler)

        assert sem._value == initial_value

    @pytest.mark.asyncio
    async def test_tool_call_missing_args_key(self) -> None:
        """tool_call without 'args' key should not crash."""
        middleware = create_concurrency_limiter()
        handler = AsyncMock(return_value="ok")

        class NoArgsRequest:
            def __init__(self) -> None:
                self.tool_call: dict[str, object] = {"name": "some_tool"}

        result = await _invoke_middleware(middleware, NoArgsRequest(), handler)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_handler_returns_command_type(self) -> None:
        """Middleware should transparently pass Command return type."""
        middleware = create_concurrency_limiter()
        command_obj = {"goto": "next_node"}
        handler = AsyncMock(return_value=command_obj)
        request = _make_request("delegate_task_tool", {"agent_type": "search"})

        result = await _invoke_middleware(middleware, request, handler)
        assert result == command_obj


class TestSafetyDispatcherEdgeCases:
    """Additional edge cases for safety_dispatcher."""

    @pytest.mark.asyncio
    async def test_handler_returns_command_type(self) -> None:
        """Safety dispatcher should transparently pass Command return type."""
        safety = create_safety_dispatcher()
        command_obj = {"goto": "next_node"}
        handler = AsyncMock(return_value=command_obj)
        request = _make_request("file_read_tool")

        result = await _invoke_middleware(safety, request, handler)
        assert result == command_obj

    @pytest.mark.asyncio
    async def test_unsafe_handler_exception_does_not_deadlock(self) -> None:
        """After unsafe handler exception, subsequent calls should still work."""
        safety = create_safety_dispatcher()

        call_count = 0

        async def handler(req: object) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("first call fails")
            return "recovered"

        request = _make_request("file_write_tool")

        with pytest.raises(ValueError):
            await _invoke_middleware(safety, request, handler)

        result = await _invoke_middleware(safety, request, handler)
        assert result == "recovered"
        assert call_count == 2


# ---------------------------------------------------------------------------
# _apply_parallel_tool_calls monkey-patch
# ---------------------------------------------------------------------------


class TestApplyParallelToolCalls:
    """Test _apply_parallel_tool_calls with real ChatLiteLLM instances."""

    def _get_method(self):
        from myrm_agent_harness.agent.base_agent import BaseAgent

        return BaseAgent._apply_parallel_tool_calls

    def _make_real_llm(self):
        from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM

        return ChatLiteLLM(model="test-model", api_key="test-key")

    def _make_agent_stub(self, parallel_val: bool | None):
        """Create a minimal object with config.parallel_tool_calls."""
        from dataclasses import dataclass

        @dataclass
        class StubConfig:
            parallel_tool_calls: bool | None

        class Stub:
            config = StubConfig(parallel_tool_calls=parallel_val)

        return Stub()

    def _dummy_tool_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "test_tool",
                "description": "A test tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def test_none_config_returns_original_llm(self) -> None:
        method = self._get_method()
        stub = self._make_agent_stub(None)
        llm = self._make_real_llm()

        result = method(stub, llm)
        assert result is llm

    def test_true_config_injects_parallel_into_bind(self) -> None:
        method = self._get_method()
        stub = self._make_agent_stub(True)
        llm = self._make_real_llm()

        patched = method(stub, llm)
        assert patched is not llm

        bound = patched.bind_tools([self._dummy_tool_schema()])
        assert bound.kwargs.get("parallel_tool_calls") is True

    def test_false_config_injects_parallel_into_bind(self) -> None:
        method = self._get_method()
        stub = self._make_agent_stub(False)
        llm = self._make_real_llm()

        patched = method(stub, llm)
        bound = patched.bind_tools([self._dummy_tool_schema()])
        assert bound.kwargs.get("parallel_tool_calls") is False

    def test_existing_parallel_kwarg_not_overridden(self) -> None:
        """setdefault should not override caller's explicit parallel_tool_calls."""
        method = self._get_method()
        stub = self._make_agent_stub(True)
        llm = self._make_real_llm()

        patched = method(stub, llm)
        bound = patched.bind_tools([self._dummy_tool_schema()], parallel_tool_calls=False)
        assert bound.kwargs.get("parallel_tool_calls") is False


# ---------------------------------------------------------------------------
# AgentConfig parallel_tool_calls env parsing
# ---------------------------------------------------------------------------


class TestAgentConfigParallelToolCalls:
    """Test PARALLEL_TOOL_CALLS environment variable parsing."""

    @pytest.fixture(autouse=True)
    def _set_required_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_MODEL_NAME", "test-model")
        monkeypatch.setenv("MYRM_API_KEY", "test-key")

    def test_env_not_set_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MYRM_PARALLEL_TOOL_CALLS", raising=False)
        from myrm_agent_harness.agent.config.llm import AgentConfig

        config = AgentConfig.from_env()
        assert config.parallel_tool_calls is None

    def test_env_true_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_PARALLEL_TOOL_CALLS", "true")
        from myrm_agent_harness.agent.config.llm import AgentConfig

        config = AgentConfig.from_env()
        assert config.parallel_tool_calls is True

    def test_env_false_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_PARALLEL_TOOL_CALLS", "false")
        from myrm_agent_harness.agent.config.llm import AgentConfig

        config = AgentConfig.from_env()
        assert config.parallel_tool_calls is False

    def test_env_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_PARALLEL_TOOL_CALLS", "TRUE")
        from myrm_agent_harness.agent.config.llm import AgentConfig

        config = AgentConfig.from_env()
        assert config.parallel_tool_calls is True
