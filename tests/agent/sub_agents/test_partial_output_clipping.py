"""A failed sub-agent attempt hands the parent at most twice the error budget of its streamed text.

Every failure branch of the retry loop returns the text the attempt streamed as ``SubAgentResult.result``;
that text becomes the parent model's tool result, so an oversized answer is cut to its head and marked.
The LLM-error and budget branches' cut is covered in ``test_partial_progress_on_failure.py``.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.executor_helpers import attach_partial_output
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentStatus

_MAX_ERROR_CHARS = 50
_CLIP_AT = _MAX_ERROR_CHARS * 2
_MARKER = "\n…[truncated]"

_FAILURES = [
    pytest.param(TimeoutError, SubAgentStatus.TIMED_OUT, id="timeout"),
    pytest.param(lambda: RuntimeError("boom"), SubAgentStatus.FAILED, id="other"),
]


async def _failed_result(make_error: object, streamed: str):
    """Run the retry loop once against an attempt that fails after streaming ``streamed``."""
    error = make_error()
    attach_partial_output(error, streamed)

    parent_agent = MagicMock()
    parent_agent._subagent_manager = None
    parent_agent._last_context = {}
    config = SubagentConfig(
        system_prompt="test",
        timeout_seconds=10,
        max_retries=1,
        retry_backoff_seconds=0,
        max_error_chars=_MAX_ERROR_CHARS,
    )
    with patch.object(SubagentExecutor, "_run_single_attempt", side_effect=error):
        return await SubagentExecutor().run_with_retry(
            task_id="clip",
            agent_type="worker",
            task_description="task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=time.time(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            children_steering={},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(("make_error", "status"), _FAILURES)
async def test_oversized_text_is_cut_to_its_head_and_marked(make_error: object, status: SubAgentStatus) -> None:
    streamed = "x" * (_CLIP_AT + 30)

    result = await _failed_result(make_error, streamed)

    assert result.success is False
    assert result.status is status
    assert result.result == streamed[:_CLIP_AT] + _MARKER


@pytest.mark.asyncio
@pytest.mark.parametrize(("make_error", "status"), _FAILURES)
async def test_text_within_the_budget_is_returned_unchanged(make_error: object, status: SubAgentStatus) -> None:
    streamed = "y" * _CLIP_AT

    result = await _failed_result(make_error, streamed)

    assert result.status is status
    assert result.result == streamed


@pytest.mark.asyncio
async def test_a_failure_that_streamed_nothing_returns_empty_text() -> None:
    result = await _failed_result(lambda: RuntimeError("boom"), "")

    assert result.result == ""
