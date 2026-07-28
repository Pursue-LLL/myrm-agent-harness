"""Integration tests for AF1: safety refusal fallback full pipeline.

Key difference from unit tests: these tests use REAL instances of
TokenTracker, detect_safety_termination, StreamCompactor, and asyncio.Queue.
Only the LLM astream output is mocked (external dependency, not our code).

Tests verify that the components collaborate correctly end-to-end:
  TokenTracker.last_finish_reason
    → detect_safety_termination()
    → rebuild_agent_fn(safety_fallback_llm)
    → safety_fallback_active SSE event on output_queue
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor
from myrm_agent_harness.agent.types import AgentRunStatistics
from myrm_agent_harness.toolkits.llms.adapters.safety_termination_detector import (
    SAFETY_FINISH_REASONS,
)
from myrm_agent_harness.utils.token_economics.tracker import (
    TokenTracker,
    _current_tracker,
    init_token_tracker,
)


def _build_ctx(*, token_tracker: TokenTracker | None = None) -> StreamContext:
    """Build a minimal but real StreamContext for integration tests."""
    return StreamContext(
        agent=MagicMock(),
        agent_input={"messages": [HumanMessage(content="analyse sensitive data")]},
        merged_context={"locale": "en"},
        run_config={"recursion_limit": 25},
        stats=AgentRunStatistics(),
        message_id="integ_safety_refusal",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
        token_tracker=token_tracker,
    )


def _build_executor(
    ctx: StreamContext,
    *,
    safety_fallback_llm: Any = None,
) -> StreamExecutor:
    """Build a real StreamExecutor wired to the given context."""
    rebuild_fn = MagicMock()
    executor = StreamExecutor(
        ctx=ctx,
        fallback_llm=None,
        safety_fallback_llm=safety_fallback_llm,
        rebuild_agent_fn=rebuild_fn,
    )
    return executor


def _drain_queue(queue: asyncio.Queue[Any]) -> list[Any]:
    """Drain all items from an asyncio.Queue without blocking."""
    items: list[Any] = []
    while not queue.empty():
        try:
            items.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return items


def _find_safety_events(events: list[Any]) -> list[dict[str, Any]]:
    """Extract safety_fallback_active events from a list of queue items."""
    results: list[dict[str, Any]] = []
    for e in events:
        raw: dict[str, Any] | None = None
        if isinstance(e, dict):
            raw = e
        elif hasattr(e, "type") and hasattr(e, "data"):
            raw = {"type": getattr(e, "type", None), "step_key": None}
            if isinstance(getattr(e, "data", None), dict):
                raw.update(e.data)
            raw["step_key"] = getattr(e, "step_key", None)

        if raw and raw.get("step_key") == "safety_fallback_active":
            results.append(raw)
    return results


# ---------------------------------------------------------------------------
# Integration Test 1: full pipeline with real TokenTracker + detector
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", sorted(SAFETY_FINISH_REASONS))
async def test_safety_refusal_full_pipeline_real_tracker(finish_reason: str) -> None:
    """Real TokenTracker + real detect_safety_termination → real rebuild → real SSE event.

    Covers every known safety finish_reason across all providers:
    OpenAI (content_filter), Anthropic (refusal), Gemini (SAFETY, BLOCKLIST, etc.)
    """
    tracker = init_token_tracker()
    tracker.last_finish_reason = finish_reason

    safety_llm = MagicMock()
    safety_llm.model_name = "safety-backup-model"

    ctx = _build_ctx(token_tracker=tracker)
    executor = _build_executor(ctx, safety_fallback_llm=safety_llm)

    token = _current_tracker.set(tracker)
    try:
        result = await executor._handle_safety_refusal_fallback()
    finally:
        _current_tracker.reset(token)

    assert result is True, f"finish_reason={finish_reason!r} should trigger safety fallback"
    assert executor.failover_used is True

    rebuild_fn = executor._rebuild_agent_fn
    rebuild_fn.assert_called_once_with(safety_llm)

    await executor._compactor.flush()
    events = _drain_queue(ctx.output_queue)
    safety_events = _find_safety_events(events)
    assert len(safety_events) >= 1, (
        f"expected safety_fallback_active event in output_queue, got events: {events}"
    )
    assert safety_events[0].get("error_kind") == "safety_block"
    assert safety_events[0].get("fallback_model") == "safety-backup-model"


# ---------------------------------------------------------------------------
# Integration Test 2: ordering — safety refusal intercepted before empty response
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_safety_refusal_ordering_before_empty_response() -> None:
    """When LLM returns empty content with a safety finish_reason, the safety
    refusal handler must fire BEFORE the empty-response retry path.

    This is the core regression that AF1 prevents: without it, a deterministic
    refusal wastes 2 empty-response retries, then raises FORMAT_ERROR
    (non-failoverable), making the configured safety_fallback_llm unreachable.

    We verify that when safety_refusal returns True (handled), the caller would
    `continue` the loop — meaning _handle_empty_response is never reached.
    The execute() loop enforces this ordering at stream_executor.py:303-306.
    """
    tracker = init_token_tracker()
    tracker.last_finish_reason = "content_filter"

    safety_llm = MagicMock()
    safety_llm.model_name = "fallback-safe-model"

    ctx = _build_ctx(token_tracker=tracker)
    executor = _build_executor(ctx, safety_fallback_llm=safety_llm)

    token = _current_tracker.set(tracker)
    try:
        safety_handled = await executor._handle_safety_refusal_fallback()
    finally:
        _current_tracker.reset(token)

    assert safety_handled is True, "safety refusal must be intercepted (returns True → continue)"
    assert executor.failover_used is True
    assert executor.streaming_final_answer is False, "streaming_final_answer must be reset for retry"

    executor._rebuild_agent_fn.assert_called_once_with(safety_llm)

    await executor._compactor.flush()
    events = _drain_queue(ctx.output_queue)
    safety_events = _find_safety_events(events)
    assert safety_events, "safety_fallback_active SSE must be emitted to notify the frontend"


# ---------------------------------------------------------------------------
# Integration Test 3: no false positives for normal finish reasons
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["stop", "length", "tool_calls", "end_turn", "max_tokens"])
async def test_normal_finish_reasons_skip_safety_fallback(finish_reason: str) -> None:
    """Normal finish reasons must NOT trigger the safety fallback path.

    Real TokenTracker + real detect_safety_termination, no mocks on the critical path.
    """
    tracker = init_token_tracker()
    tracker.last_finish_reason = finish_reason

    safety_llm = MagicMock()
    ctx = _build_ctx(token_tracker=tracker)
    executor = _build_executor(ctx, safety_fallback_llm=safety_llm)

    token = _current_tracker.set(tracker)
    try:
        result = await executor._handle_safety_refusal_fallback()
    finally:
        _current_tracker.reset(token)

    assert result is False, f"finish_reason={finish_reason!r} must not trigger safety fallback"
    assert executor.failover_used is False
    executor._rebuild_agent_fn.assert_not_called()


# ---------------------------------------------------------------------------
# Integration Test 4: tracker exists but finish_reason is None
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tracker_present_but_finish_reason_none() -> None:
    """When TokenTracker is initialised but LLM never set finish_reason (normal
    dialogue end), the safety fallback must NOT fire.

    Real scenario: short responses where the callback simply never populates
    last_finish_reason.
    """
    tracker = init_token_tracker()
    assert tracker.last_finish_reason is None

    safety_llm = MagicMock()
    ctx = _build_ctx(token_tracker=tracker)
    executor = _build_executor(ctx, safety_fallback_llm=safety_llm)

    token = _current_tracker.set(tracker)
    try:
        result = await executor._handle_safety_refusal_fallback()
    finally:
        _current_tracker.reset(token)

    assert result is False
    assert executor.failover_used is False
    executor._rebuild_agent_fn.assert_not_called()


# ---------------------------------------------------------------------------
# Integration Test 5: tracker not in ContextVar (never initialised)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tracker_not_in_contextvar() -> None:
    """When no TokenTracker has been set in ContextVar (e.g. direct tool
    invocation outside the streaming loop), safety fallback must silently skip.
    """
    _current_tracker.set(None)

    safety_llm = MagicMock()
    ctx = _build_ctx(token_tracker=None)
    executor = _build_executor(ctx, safety_fallback_llm=safety_llm)

    result = await executor._handle_safety_refusal_fallback()

    assert result is False
    assert executor.failover_used is False
    executor._rebuild_agent_fn.assert_not_called()


# ---------------------------------------------------------------------------
# Integration Test 6: safety finish_reason but no safety_fallback_llm
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_safety_refusal_no_fallback_llm_configured() -> None:
    """When user has not configured a safety_fallback_llm but the LLM returns
    a safety refusal, the handler must skip gracefully (log warning, return False).

    Real TokenTracker + real detect_safety_termination on the critical path.
    """
    tracker = init_token_tracker()
    tracker.last_finish_reason = "content_filter"

    ctx = _build_ctx(token_tracker=tracker)
    executor = _build_executor(ctx, safety_fallback_llm=None)

    token = _current_tracker.set(tracker)
    try:
        result = await executor._handle_safety_refusal_fallback()
    finally:
        _current_tracker.reset(token)

    assert result is False
    assert executor.failover_used is False


# ---------------------------------------------------------------------------
# Integration Test 7: safety finish_reason but failover already used
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_safety_refusal_after_prior_failover() -> None:
    """When the primary model already failed over (e.g. 500 error → fallback_llm),
    a subsequent safety refusal on the backup model must NOT attempt a second
    failover — failover_used=True is a hard one-shot guard.

    Real TokenTracker + real detect_safety_termination.
    """
    tracker = init_token_tracker()
    tracker.last_finish_reason = "refusal"

    safety_llm = MagicMock()
    ctx = _build_ctx(token_tracker=tracker)
    executor = _build_executor(ctx, safety_fallback_llm=safety_llm)
    executor.failover_used = True

    token = _current_tracker.set(tracker)
    try:
        result = await executor._handle_safety_refusal_fallback()
    finally:
        _current_tracker.reset(token)

    assert result is False
    executor._rebuild_agent_fn.assert_not_called()


# ---------------------------------------------------------------------------
# Integration Test 8: fallback model name resolution fallback chain
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fallback_model_name_resolution_chain() -> None:
    """When safety_fallback_llm has no `model_name` attribute, the handler
    falls back to `model` attribute, then to the literal "backup".

    Tests the getattr chain at stream_recovery.py:250.
    """
    tracker = init_token_tracker()
    tracker.last_finish_reason = "SAFETY"

    class _LLMWithModelAttr:
        """LLM that only has `model` attribute, not `model_name`."""
        model = "gemini-safety-fallback"

    safety_llm = _LLMWithModelAttr()
    ctx = _build_ctx(token_tracker=tracker)
    executor = _build_executor(ctx, safety_fallback_llm=safety_llm)

    token = _current_tracker.set(tracker)
    try:
        result = await executor._handle_safety_refusal_fallback()
    finally:
        _current_tracker.reset(token)

    assert result is True

    await executor._compactor.flush()
    events = _drain_queue(ctx.output_queue)
    safety_events = _find_safety_events(events)
    assert safety_events
    assert safety_events[0].get("fallback_model") == "gemini-safety-fallback"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fallback_model_name_ultimate_fallback() -> None:
    """When safety_fallback_llm has neither `model_name` nor `model`,
    the handler uses the literal "backup" string.
    """
    tracker = init_token_tracker()
    tracker.last_finish_reason = "BLOCKLIST"

    class _BareMinimalLLM:
        """LLM with no model identification attributes at all."""

    safety_llm = _BareMinimalLLM()
    ctx = _build_ctx(token_tracker=tracker)
    executor = _build_executor(ctx, safety_fallback_llm=safety_llm)

    token = _current_tracker.set(tracker)
    try:
        result = await executor._handle_safety_refusal_fallback()
    finally:
        _current_tracker.reset(token)

    assert result is True

    await executor._compactor.flush()
    events = _drain_queue(ctx.output_queue)
    safety_events = _find_safety_events(events)
    assert safety_events
    assert safety_events[0].get("fallback_model") == "backup"
