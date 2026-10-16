"""A recovery restart inside a sub-agent run must not leave the replayed segment in the sub-agent's answer.

The child agent runs on the same ``StreamExecutor`` as the parent, so truncation retries, context-pressure
handling and model switches announce ``restart`` on its event stream. What the executor hands back (the
result, or ``partial_output`` on failure) is the text the parent model reads as a tool result.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.executor_helpers import attach_partial_output, read_partial_output
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig
from myrm_agent_harness.toolkits.llms.errors.exceptions import MyrmLLMError

_NO_CUT = 10_000
_RESTART = {"type": AgentEventType.STATUS.value, "restart": True, "data": {}}


def _message(text: str) -> dict[str, object]:
    return {"type": AgentEventType.MESSAGE.value, "data": text}


async def _attempt_failing_after(events: list[dict[str, object]]) -> str:
    """Run one attempt whose child streams ``events`` and then reports an error; return ``partial_output``."""
    parent_agent = MagicMock()
    parent_agent._subagent_manager = None
    parent_agent._last_context = {}

    async def child_run(**_kwargs: object) -> AsyncIterator[dict[str, object]]:
        for event in events:
            yield event
        yield {"type": AgentEventType.ERROR.value, "error": "provider down"}

    child_agent = MagicMock()
    child_agent.run = child_run

    config = SubagentConfig(system_prompt="test", timeout_seconds=10, max_retries=1, retry_backoff_seconds=0)
    with (
        patch(
            "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
            return_value=child_agent,
        ),
        pytest.raises(MyrmLLMError) as failure,
    ):
        await SubagentExecutor()._run_single_attempt(
            task_id="restart-attempt",
            agent_type="worker",
            task_description="task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=0.0,
            parent_tracker=None,
            parent_taint=MagicMock(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            fire_hook=AsyncMock(),
            hook_event_cls=MagicMock(),
        )
    return read_partial_output(failure.value, _NO_CUT)


@pytest.mark.asyncio
async def test_restart_drops_only_the_segment_in_flight() -> None:
    """Text before the last tool step stays; the half-written segment after it is replaced by its replay."""
    partial = await _attempt_failing_after(
        [
            _message("Looking it up. "),
            {"type": AgentEventType.TOOL_START.value, "data": {}},
            _message("The price is 1"),
            _RESTART,
            _message("The price is 12 USD."),
        ]
    )

    assert partial == "Looking it up. The price is 12 USD."


@pytest.mark.asyncio
async def test_without_restart_every_message_chunk_is_kept() -> None:
    """Plain streaming is unchanged: chunks concatenate in order."""
    partial = await _attempt_failing_after([_message("step1 "), _message("step2 ")])

    assert partial == "step1 step2 "


def test_partial_output_roundtrip_keeps_the_first_record_and_defaults_to_empty() -> None:
    """The retry loop reads back what the attempt recorded; a missing or non-text record reads as empty."""
    error = RuntimeError("boom")
    assert read_partial_output(error, _NO_CUT) == ""

    attach_partial_output(error, "first")
    attach_partial_output(error, "second")
    assert read_partial_output(error, _NO_CUT) == "first"

    error.partial_output = 42  # type: ignore[attr-defined]
    assert read_partial_output(error, _NO_CUT) == ""
