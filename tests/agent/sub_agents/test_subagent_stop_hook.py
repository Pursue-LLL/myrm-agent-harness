"""Every sub-agent run that fires SUBAGENT_START ends with a SUBAGENT_STOP.

The hook pair is the contract external subscribers use to open and close a per-run span, so each way one
attempt can end (a returned result of any status, or an exception of any class) must close it. A cancellation
landing while the STOP is still being delivered adds a final ``cancelled`` STOP, so delivery is at-least-once
and the last STOP carries the run's final status; a second cancellation inside the cancel path's own hook
delivery is the one case that leaves no STOP.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.hooks.executor import HookExecutor
from myrm_agent_harness.agent.hooks.registry import HookRegistry
from myrm_agent_harness.agent.hooks.session_access import set_hook_executor
from myrm_agent_harness.agent.hooks.types import HookEvent
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.manager import SubagentManager
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentBudgetExceededError,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
    WorkspacePolicy,
)
from myrm_agent_harness.core.hooks.types import CallableHookDefinition, HookCallable, HookResult
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
def _patched(attempt: AsyncMock | None, fire_hook: Callable[..., Awaitable[object]] | None = None) -> Iterator[None]:
    """Replace the single attempt (unless the real pipeline should run) and optionally the hook dispatcher."""
    with ExitStack() as stack:
        if fire_hook is not None:
            stack.enter_context(patch("myrm_agent_harness.agent.hooks.executor.fire_hook", fire_hook))
        if attempt is not None:
            stack.enter_context(patch.object(SubagentExecutor, "_run_single_attempt", attempt))
        yield


async def _invoke(config: SubagentConfig, context: dict[str, object] | None = None) -> SubAgentResult:
    parent_agent = MagicMock()
    parent_agent._subagent_manager = None
    parent_agent._last_context = {}
    return await SubagentExecutor().run_with_retry(
        task_id="stop-pair",
        agent_type="worker",
        task_description="task",
        config=config,
        context=context or {},
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
    with _patched(attempt, fire_hook):
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
async def test_a_cancellation_during_stop_delivery_still_gives_every_subscriber_a_final_stop() -> None:
    """Hooks run one after another; a cancel landing in the first must not leave the second without a STOP."""
    seen: dict[str, list[tuple[str, object]]] = {"slow": [], "fast": []}
    stop_started = asyncio.Event()
    completed = _SUCCESS_RETURNS[0].values[0]

    def subscriber(name: str, *, slow_first_stop: bool) -> HookCallable:
        async def hook(event: str, payload: dict[str, object]) -> HookResult:
            seen[name].append((event, payload.get("status")))
            stops = [entry for entry in seen[name] if entry[0] == HookEvent.SUBAGENT_STOP]
            if slow_first_stop and event == HookEvent.SUBAGENT_STOP and len(stops) == 1:
                stop_started.set()
                await asyncio.sleep(30)
            return HookResult(hook_type="callable", success=True)

        return hook

    registry = HookRegistry()
    for event in (HookEvent.SUBAGENT_START, HookEvent.SUBAGENT_STOP, HookEvent.SUBAGENT_CANCEL_COMPLETE):
        registry.register(event, CallableHookDefinition(fn=subscriber("slow", slow_first_stop=True), priority=10))
        registry.register(event, CallableHookDefinition(fn=subscriber("fast", slow_first_stop=False), priority=0))
    set_hook_executor(HookExecutor(registry))
    try:
        with _patched(AsyncMock(return_value=completed)):
            run = asyncio.create_task(_invoke(_config()))
            await stop_started.wait()
            run.cancel()
            result = await run
    finally:
        set_hook_executor(None)

    assert result.status is SubAgentStatus.CANCELLED
    for entries in seen.values():
        stops = [status for event, status in entries if event == HookEvent.SUBAGENT_STOP]
        assert stops, "every subscriber that saw START must see a STOP"
        assert stops[-1] == "cancelled"


class _FakeIsolation:
    """Stand-in for ``isolated_workspace``: yields a child path and a no-op sync-back."""

    async def __aenter__(self) -> tuple[str, Callable[[], None]]:
        return "/child", lambda: None

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.mark.asyncio
async def test_the_stop_is_delivered_before_the_isolated_workspace_is_merged_back() -> None:
    """Subscribers hear about the finished run before its workspace changes land in the parent."""
    order: list[str] = []

    async def record_hook(event: str, _payload: dict[str, object]) -> None:
        order.append(event)

    async def record_sync_back(*, result: SubAgentResult, **_: object) -> SubAgentResult:
        order.append("sync_back")
        return result

    config = SubagentConfig(
        system_prompt="test",
        timeout_seconds=10,
        max_retries=1,
        retry_backoff_seconds=0,
        workspace_policy=WorkspacePolicy.ISOLATED_COPY,
    )
    with (
        patch(
            "myrm_agent_harness.agent.sub_agents.workspace_isolation.isolated_workspace",
            return_value=_FakeIsolation(),
        ),
        patch(
            "myrm_agent_harness.agent.sub_agents.executor_retry_mixin._apply_immediate_isolated_sync_back",
            record_sync_back,
        ),
        _patched(AsyncMock(return_value=_SUCCESS_RETURNS[0].values[0]), record_hook),
    ):
        await _invoke(config, {"workspace_path": "/parent"})

    assert order == [HookEvent.SUBAGENT_START, HookEvent.SUBAGENT_STOP, "sync_back"]


@pytest.mark.asyncio
async def test_a_run_killed_by_the_hard_timeout_reports_timed_out_while_its_hooks_see_a_cancellation() -> None:
    """The manager's deadline cancels the run; its result says timed out, the executor's STOP says cancelled."""
    config = _config()
    object.__setattr__(config, "timeout_seconds", 0.25)  # hard deadline: 0.75s

    async def hang(*_: object, **__: object) -> None:
        await asyncio.sleep(60)

    fire_hook = AsyncMock()
    with (
        patch("myrm_agent_harness.agent.hooks.graceful_shutdown.get_shutdown_manager"),
        _patched(AsyncMock(side_effect=hang), fire_hook),
    ):
        manager = SubagentManager(parent_agent=MagicMock())
        result = await manager._run_subagent(
            task_id="stop-pair",
            agent_type="worker",
            task_description="task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
            trace_id="trace-1",
        )

    assert result.status is SubAgentStatus.TIMED_OUT
    assert result.error == "Hard timeout after 0.75s"
    hooks = [(call.args[0], call.args[1]) for call in fire_hook.await_args_list]
    assert [event for event, _ in hooks] == [
        HookEvent.SUBAGENT_START,
        HookEvent.SUBAGENT_CANCEL_COMPLETE,
        HookEvent.SUBAGENT_STOP,
    ]
    assert hooks[2][1]["status"] == "cancelled"
