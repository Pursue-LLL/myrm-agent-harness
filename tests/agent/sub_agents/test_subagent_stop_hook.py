"""Every sub-agent run that fires SUBAGENT_START ends with exactly one SUBAGENT_STOP.

The hook pair is the contract external subscribers use to open and close a per-run span, so each way a run
can fail (timeout, LLM error, budget exceeded, any other error, no attempt made) must close it.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.hooks.types import HookEvent
from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentBudgetExceededError,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason
from myrm_agent_harness.toolkits.llms.errors.exceptions import MyrmLLMError

_FAILURES = [
    pytest.param(TimeoutError, id="timeout"),
    pytest.param(lambda: MyrmLLMError(error_code=FailoverReason.OVERLOADED, default_msg="provider down"), id="llm"),
    pytest.param(lambda: SubagentBudgetExceededError("over budget"), id="budget"),
    pytest.param(lambda: RuntimeError("boom"), id="other"),
]


async def _run(
    config: SubagentConfig, attempt: AsyncMock
) -> tuple[SubAgentResult, list[tuple[str, dict[str, object]]]]:
    """Run the retry loop once and return its result with the hooks it fired, in order."""
    fire_hook = AsyncMock()
    parent_agent = MagicMock()
    parent_agent._subagent_manager = None
    parent_agent._last_context = {}
    with (
        patch.object(SubagentExecutor, "_run_single_attempt", attempt),
        patch("myrm_agent_harness.agent.hooks.executor.fire_hook", fire_hook),
    ):
        result = await SubagentExecutor().run_with_retry(
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
        )
    return result, [(call.args[0], call.args[1]) for call in fire_hook.await_args_list]


@pytest.mark.asyncio
@pytest.mark.parametrize("make_error", _FAILURES)
async def test_a_failed_run_is_closed_by_one_stop_carrying_the_result(make_error: Callable[[], BaseException]) -> None:
    config = SubagentConfig(system_prompt="test", timeout_seconds=10, max_retries=1, retry_backoff_seconds=0)

    result, hooks = await _run(config, AsyncMock(side_effect=make_error()))

    assert result.success is False
    assert [event for event, _ in hooks] == [HookEvent.SUBAGENT_START, HookEvent.SUBAGENT_STOP]
    payload = hooks[1][1]
    assert payload == {
        "task_id": "stop-pair",
        "agent_type": "worker",
        "success": False,
        "error": result.error,
        "duration_seconds": result.duration_seconds,
        "trace_id": result.trace_id,
    }


@pytest.mark.asyncio
async def test_a_run_that_makes_no_attempt_is_still_closed() -> None:
    config = SubagentConfig(system_prompt="test", max_retries=0, retry_backoff_seconds=0)
    attempt = AsyncMock()

    result, hooks = await _run(config, attempt)

    attempt.assert_not_awaited()
    assert result.status is SubAgentStatus.FAILED
    assert [event for event, _ in hooks] == [HookEvent.SUBAGENT_START, HookEvent.SUBAGENT_STOP]
