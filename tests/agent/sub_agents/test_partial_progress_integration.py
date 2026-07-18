"""Integration test: Subagent Partial Progress Return on Failure — real event pipeline.

Exercises the real executor_attempt_mixin → EventForwarder.check_budget → except Exception
→ executor_retry_mixin → SubAgentResult(result=partial) chain.

Only build_child_agent is mocked (to avoid real LLM). All event processing, budget checks,
partial_output attachment, retry logic, hook firing, and result construction run through
real production code paths.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentBudgetExceededError,
    SubagentConfig,
    SubAgentStatus,
)
from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason
from myrm_agent_harness.toolkits.llms.errors.exceptions import MyrmLLMError

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class _StubLLM:
    """Minimal LLM stub for BaseAgent construction."""

    def bind(self, **kwargs: object) -> "_StubLLM":
        return self

    def bind_tools(self, tools: list[object], **kwargs: object) -> "_StubLLM":
        return self

    async def ainvoke(self, messages: list[object], config: object = None) -> object:
        from langchain_core.messages import AIMessage
        return AIMessage(content="stub")


def _make_child_agent_budget_exceeded(budget_tokens: int):
    """Create a fake child agent whose run() yields messages then exceeds budget via TOKEN_USAGE."""
    child = MagicMock()
    child.last_run_stats = MagicMock(token_usage=None)
    child.checkpointer = None

    async def mock_run(**kwargs: object):
        yield {"type": AgentEventType.MESSAGE.value, "data": "I am working on the analysis. "}
        yield {"type": AgentEventType.MESSAGE.value, "data": "Here are initial findings..."}
        yield {
            "type": AgentEventType.TOKEN_USAGE.value,
            "data": {"usage": {"total_tokens": budget_tokens + 100, "total_cost_usd": 0.001}},
        }
        yield {"type": AgentEventType.MESSAGE.value, "data": " (this should not be reached)"}

    child.run = mock_run
    return child


def _make_child_agent_error_event():
    """Create a fake child agent whose run() yields messages then an ERROR event."""
    child = MagicMock()
    child.last_run_stats = MagicMock(token_usage=None)
    child.checkpointer = None

    async def mock_run(**kwargs: object):
        yield {"type": AgentEventType.MESSAGE.value, "data": "Starting research..."}
        yield {"type": AgentEventType.MESSAGE.value, "data": " Found 3 results."}
        yield {"type": AgentEventType.ERROR.value, "error": "model rate limited"}

    child.run = mock_run
    return child


def _make_child_agent_runtime_error():
    """Create a fake child agent whose run() yields messages then raises RuntimeError."""
    child = MagicMock()
    child.last_run_stats = MagicMock(token_usage=None)
    child.checkpointer = None

    async def mock_run(**kwargs: object):
        yield {"type": AgentEventType.MESSAGE.value, "data": "Processing chunk A. "}
        yield {"type": AgentEventType.MESSAGE.value, "data": "Processing chunk B."}
        raise RuntimeError("unexpected internal error")

    child.run = mock_run
    return child


@pytest.fixture
def executor() -> SubagentExecutor:
    return SubagentExecutor()


@pytest.fixture
def parent_agent() -> BaseAgent:
    return BaseAgent(llm=_StubLLM())


async def test_budget_exceeded_real_pipeline_returns_partial(
    executor: SubagentExecutor, parent_agent: BaseAgent
) -> None:
    """Real EventForwarder.check_budget triggers SubagentBudgetExceededError.

    Verifies the full pipeline: event streaming → budget check → exception with partial
    → retry mixin catch → SubAgentResult(result=partial, status=CANCELLED_BY_BUDGET).
    """
    config = SubagentConfig(
        system_prompt="research assistant",
        budget_tokens=50,
        timeout_seconds=30,
        max_retries=1,
        retry_backoff_seconds=0,
        max_error_chars=200,
    )

    child = _make_child_agent_budget_exceeded(budget_tokens=50)

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=child,
    ):
        result = await executor.run_with_retry(
            task_id="integration-budget",
            agent_type="researcher",
            task_description="Analyze market trends",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=time.time(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            children_steering={},
        )

    assert result.success is False
    assert result.status == SubAgentStatus.CANCELLED_BY_BUDGET
    assert "I am working on the analysis." in result.result
    assert "Here are initial findings..." in result.result
    assert "should not be reached" not in result.result
    assert "Budget exceeded" in result.error


async def test_error_event_real_pipeline_returns_partial(
    executor: SubagentExecutor, parent_agent: BaseAgent
) -> None:
    """ERROR event triggers MyrmLLMError with partial_output.

    Verifies: ERROR event → MyrmLLMError(partial_output=messages) → retry mixin
    → SubAgentResult(result=partial, status=FAILED).
    """
    config = SubagentConfig(
        system_prompt="researcher",
        timeout_seconds=30,
        max_retries=1,
        retry_backoff_seconds=0,
        max_error_chars=200,
    )

    child = _make_child_agent_error_event()

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=child,
    ):
        result = await executor.run_with_retry(
            task_id="integration-error",
            agent_type="researcher",
            task_description="Search for data",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=time.time(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            children_steering={},
        )

    assert result.success is False
    assert result.status == SubAgentStatus.FAILED
    assert "Starting research..." in result.result
    assert "Found 3 results." in result.result
    assert "rate limit" in result.error.lower() or "Subagent error" in result.error


async def test_runtime_error_real_pipeline_returns_partial(
    executor: SubagentExecutor, parent_agent: BaseAgent
) -> None:
    """RuntimeError during streaming → partial_output attached → SubAgentResult.

    Verifies: RuntimeError mid-stream → except Exception → partial_output = messages
    → retry mixin catch → SubAgentResult(result=partial, status=FAILED).
    """
    config = SubagentConfig(
        system_prompt="processor",
        timeout_seconds=30,
        max_retries=1,
        retry_backoff_seconds=0,
        max_error_chars=200,
    )

    child = _make_child_agent_runtime_error()

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=child,
    ):
        result = await executor.run_with_retry(
            task_id="integration-runtime",
            agent_type="processor",
            task_description="Process data",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=time.time(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            children_steering={},
        )

    assert result.success is False
    assert result.status == SubAgentStatus.FAILED
    assert "Processing chunk A." in result.result
    assert "Processing chunk B." in result.result
    assert "RuntimeError" in result.error


async def test_truncation_real_pipeline(
    executor: SubagentExecutor, parent_agent: BaseAgent
) -> None:
    """Oversized partial output is truncated by retry mixin (real path)."""
    config = SubagentConfig(
        system_prompt="writer",
        timeout_seconds=30,
        max_retries=1,
        retry_backoff_seconds=0,
        max_error_chars=50,
    )

    child = MagicMock()
    child.last_run_stats = MagicMock(token_usage=None)
    child.checkpointer = None

    long_content = "A" * 200

    async def mock_run(**kwargs: object):
        yield {"type": AgentEventType.MESSAGE.value, "data": long_content}
        yield {"type": AgentEventType.ERROR.value, "error": "context full"}

    child.run = mock_run

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=child,
    ):
        result = await executor.run_with_retry(
            task_id="integration-trunc",
            agent_type="writer",
            task_description="Write essay",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=time.time(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            children_steering={},
        )

    assert result.success is False
    assert result.result.endswith("\n…[truncated]")
    assert len(result.result) == 100 + len("\n…[truncated]")


async def test_hook_fired_real_pipeline(
    executor: SubagentExecutor, parent_agent: BaseAgent
) -> None:
    """SUBAGENT_STOP hook fires through real code path on budget exceeded."""
    config = SubagentConfig(
        system_prompt="helper",
        budget_tokens=10,
        timeout_seconds=30,
        max_retries=1,
        retry_backoff_seconds=0,
    )

    child = _make_child_agent_budget_exceeded(budget_tokens=10)

    hook_calls: list[tuple[object, dict[str, object]]] = []

    async def capture_hook(event: object, payload: dict[str, object]) -> None:
        hook_calls.append((event, payload))

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=child,
    ), patch(
        "myrm_agent_harness.agent.hooks.executor.fire_hook",
        side_effect=capture_hook,
    ):
        result = await executor.run_with_retry(
            task_id="integration-hook",
            agent_type="helper",
            task_description="Help user",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=time.time(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            children_steering={},
        )

    assert result.success is False
    stop_calls = [(ev, p) for ev, p in hook_calls if "stop" in str(ev).lower()]
    assert len(stop_calls) >= 1
    _, stop_payload = stop_calls[0]
    assert stop_payload["task_id"] == "integration-hook"
    assert stop_payload["success"] is False


async def test_timeout_error_real_pipeline_returns_partial(
    executor: SubagentExecutor, parent_agent: BaseAgent
) -> None:
    """TimeoutError from child_agent.run() → partial_output attached → SubAgentResult.

    Real EventForwarder is created; the timeout happens during iteration.
    """
    config = SubagentConfig(
        system_prompt="timer",
        timeout_seconds=5,
        max_retries=1,
        retry_backoff_seconds=0,
        max_error_chars=200,
    )

    child = MagicMock()
    child.last_run_stats = MagicMock(token_usage=None)
    child.checkpointer = None

    async def mock_run(**kwargs: object):
        yield {"type": AgentEventType.MESSAGE.value, "data": "Started processing. "}
        yield {"type": AgentEventType.MESSAGE.value, "data": "Partial result here."}
        raise TimeoutError("httpx read timeout")

    child.run = mock_run

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=child,
    ):
        result = await executor.run_with_retry(
            task_id="integration-timeout",
            agent_type="timer",
            task_description="Process with deadline",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=time.time(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            children_steering={},
        )

    assert result.success is False
    assert result.status == SubAgentStatus.TIMED_OUT
    assert "Started processing." in result.result
    assert "Partial result here." in result.result
    assert "Timeout" in result.error


async def test_retry_success_after_failure_no_partial_leak(
    executor: SubagentExecutor, parent_agent: BaseAgent
) -> None:
    """First attempt fails with partial, retry succeeds → clean success result."""
    config = SubagentConfig(
        system_prompt="resilient",
        timeout_seconds=30,
        max_retries=2,
        retry_backoff_seconds=0,
    )

    call_count = {"n": 0}

    def _make_child():
        child = MagicMock()
        child.last_run_stats = MagicMock(token_usage=None)
        child.checkpointer = None

        call_count["n"] += 1
        n = call_count["n"]

        async def mock_run(**kwargs: object):
            if n == 1:
                yield {"type": AgentEventType.MESSAGE.value, "data": "failed partial"}
                yield {"type": AgentEventType.ERROR.value, "error": "transient"}
            else:
                yield {"type": AgentEventType.MESSAGE.value, "data": "success output"}

        child.run = mock_run
        return child

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        side_effect=lambda *a, **kw: _make_child(),
    ):
        result = await executor.run_with_retry(
            task_id="integration-retry-ok",
            agent_type="resilient",
            task_description="Retry scenario",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=time.time(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            children_steering={},
        )

    assert result.success is True
    assert result.result == "success output"
    assert "failed partial" not in result.result
