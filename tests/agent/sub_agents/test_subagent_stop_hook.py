"""Every sub-agent run that fires SUBAGENT_START ends with exactly one SUBAGENT_STOP.

The hook pair is the contract external subscribers use to open and close a per-run span, so each way one
attempt can end (a returned result of any status, or an exception of any class) must close it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.hooks.types import HookEvent
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentBudgetExceededError,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason
from myrm_agent_harness.toolkits.llms.errors.exceptions import MyrmLLMError

_PAIR = [HookEvent.SUBAGENT_START, HookEvent.SUBAGENT_STOP]

_EXCEPTIONS = [
    pytest.param(TimeoutError, id="timeout"),
    pytest.param(lambda: MyrmLLMError(error_code=FailoverReason.OVERLOADED, default_msg="provider down"), id="llm"),
    pytest.param(lambda: SubagentBudgetExceededError("over budget"), id="budget"),
    pytest.param(lambda: RuntimeError("boom"), id="other"),
]

_FAILED_RETURN = SubAgentResult(
    success=False,
    task_id="stop-pair",
    agent_type="worker",
    error="no tools",
    duration_seconds=1.5,
    status=SubAgentStatus.FAILED,
    trace_id="trace-1",
)
_SUCCESS_RETURNS = [
    pytest.param(
        SubAgentResult(
            success=True,
            task_id="stop-pair",
            agent_type="worker",
            result="done",
            duration_seconds=2.5,
            status=SubAgentStatus.COMPLETED,
            trace_id="trace-1",
        ),
        id="completed",
    ),
    pytest.param(
        SubAgentResult(
            success=True,
            task_id="stop-pair",
            agent_type="worker",
            duration_seconds=0.5,
            status=SubAgentStatus.YIELDED,
            payload={"action_type": "swarm_fission"},
            trace_id="trace-1",
        ),
        id="yielded",
    ),
    pytest.param(
        SubAgentResult(
            success=True,
            task_id="stop-pair",
            agent_type="worker",
            duration_seconds=0.5,
            status=SubAgentStatus.PENDING_APPROVAL,
            payload={"action_type": "approval"},
            trace_id="trace-1",
        ),
        id="pending_approval",
    ),
]


@contextmanager
def _patched(fire_hook: Callable[..., Awaitable[object]], attempt: AsyncMock | None) -> Iterator[None]:
    """Replace the hook dispatcher, and the single attempt unless the real pipeline should run."""
    with ExitStack() as stack:
        stack.enter_context(patch("myrm_agent_harness.agent.hooks.executor.fire_hook", fire_hook))
        if attempt is not None:
            stack.enter_context(patch.object(SubagentExecutor, "_run_single_attempt", attempt))
        yield


async def _invoke(config: SubagentConfig) -> SubAgentResult:
    parent_agent = MagicMock()
    parent_agent._subagent_manager = None
    parent_agent._last_context = {}
    return await SubagentExecutor().run_with_retry(
        task_id="stop-pair",
        agent_type="worker",
        task_description="task",
        config=config,
        context={},
        tool_registry_getter=lambda: [],
        start_time=0.0,
        parent_agent=parent_agent,
        cancel_flags={},
        children_agents={},
        children_steering={},
        trace_id="trace-1",
    )


async def _run(
    config: SubagentConfig, attempt: AsyncMock | None = None
) -> tuple[SubAgentResult, list[tuple[str, dict[str, object]]]]:
    """Run the retry loop once and return its result with the hooks it fired, in order.

    Without ``attempt`` the real single-attempt pipeline runs.
    """
    fire_hook = AsyncMock()
    with _patched(fire_hook, attempt):
        result = await _invoke(config)
    return result, [(call.args[0], call.args[1]) for call in fire_hook.await_args_list]


def _config(tools: tuple[str, ...] = ()) -> SubagentConfig:
    return SubagentConfig(system_prompt="test", timeout_seconds=10, max_retries=1, retry_backoff_seconds=0, tools=tools)


def _failure_payload(result: SubAgentResult) -> dict[str, object]:
    return {
        "task_id": "stop-pair",
        "agent_type": "worker",
        "success": False,
        "status": result.status.value,
        "error": result.error,
        "duration_seconds": result.duration_seconds,
        "trace_id": "trace-1",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("make_error", _EXCEPTIONS)
async def test_a_run_that_raises_is_closed_by_one_stop_carrying_the_result(
    make_error: Callable[[], BaseException],
) -> None:
    result, hooks = await _run(_config(), AsyncMock(side_effect=make_error()))

    assert result.success is False
    assert [event for event, _ in hooks] == _PAIR
    assert hooks[1][1] == _failure_payload(result)


@pytest.mark.asyncio
async def test_a_run_that_makes_no_attempt_is_still_closed() -> None:
    attempt = AsyncMock()

    result, hooks = await _run(SubagentConfig(system_prompt="test", max_retries=0, retry_backoff_seconds=0), attempt)

    attempt.assert_not_awaited()
    assert result.status is SubAgentStatus.FAILED
    assert [event for event, _ in hooks] == _PAIR
    assert hooks[1][1] == _failure_payload(result)


@pytest.mark.asyncio
async def test_an_attempt_that_returns_failed_is_closed() -> None:
    result, hooks = await _run(_config(), AsyncMock(return_value=_FAILED_RETURN))

    assert result is _FAILED_RETURN
    assert [event for event, _ in hooks] == _PAIR
    assert hooks[1][1] == _failure_payload(_FAILED_RETURN)


@pytest.mark.asyncio
@pytest.mark.parametrize("returned", _SUCCESS_RETURNS)
async def test_an_attempt_that_returns_a_success_status_is_closed(returned: SubAgentResult) -> None:
    result, hooks = await _run(_config(), AsyncMock(return_value=returned))

    assert result is returned
    assert [event for event, _ in hooks] == _PAIR
    assert hooks[1][1] == {
        "task_id": "stop-pair",
        "agent_type": "worker",
        "success": True,
        "status": returned.status.value,
        "result": returned.result,
        "duration_seconds": returned.duration_seconds,
        "trace_id": "trace-1",
    }


class _StubChild:
    """Child agent whose run() streams one answer and then ends without interrupts."""

    checkpointer = None
    last_run_stats = None
    _agent = None

    async def run(self, **_: object) -> AsyncIterator[dict[str, object]]:
        yield {"type": AgentEventType.MESSAGE.value, "data": "all good"}


@pytest.mark.asyncio
async def test_the_real_success_pipeline_closes_its_run_with_the_answer() -> None:
    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=_StubChild(),
    ):
        result, hooks = await _run(_config())

    assert result.status is SubAgentStatus.COMPLETED
    assert [event for event, _ in hooks] == _PAIR
    assert hooks[1][1] == {
        "task_id": "stop-pair",
        "agent_type": "worker",
        "success": True,
        "status": "completed",
        "result": "all good",
        "duration_seconds": result.duration_seconds,
        "trace_id": "trace-1",
    }


@pytest.mark.asyncio
async def test_the_real_pipeline_closes_a_run_whose_tool_allowlist_is_empty() -> None:
    result, hooks = await _run(_config(tools=("missing_tool",)))

    assert result.status is SubAgentStatus.FAILED
    assert "no tools after filtering" in result.error
    assert [event for event, _ in hooks] == _PAIR
    assert hooks[1][1] == _failure_payload(result)


@pytest.mark.asyncio
async def test_a_cancelled_run_is_closed_by_a_stop_that_follows_cancel_complete() -> None:
    result, hooks = await _run(_config(), AsyncMock(side_effect=asyncio.CancelledError()))

    assert result.status is SubAgentStatus.CANCELLED
    assert [event for event, _ in hooks] == [
        HookEvent.SUBAGENT_START,
        HookEvent.SUBAGENT_CANCEL_COMPLETE,
        HookEvent.SUBAGENT_STOP,
    ]
    assert hooks[2][1] == _failure_payload(result)
    assert hooks[2][1]["error"] == "Cancelled"


@pytest.mark.asyncio
async def test_a_cancellation_during_stop_delivery_sends_no_second_stop() -> None:
    delivered: list[str] = []
    stop_started = asyncio.Event()
    completed = _SUCCESS_RETURNS[0].values[0]

    async def slow_stop(event: str, payload: dict[str, object]) -> None:
        delivered.append(event)
        if event == HookEvent.SUBAGENT_STOP:
            stop_started.set()
            await asyncio.sleep(30)

    with _patched(slow_stop, AsyncMock(return_value=completed)):
        run = asyncio.create_task(_invoke(_config()))
        await stop_started.wait()
        run.cancel()
        result = await run

    assert result.status is SubAgentStatus.CANCELLED
    assert delivered == [HookEvent.SUBAGENT_START, HookEvent.SUBAGENT_STOP, HookEvent.SUBAGENT_CANCEL_COMPLETE]
