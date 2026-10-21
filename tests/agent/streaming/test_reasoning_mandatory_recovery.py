"""Tests for reasoning mandatory 400 self-healing and PAAS 1305 adaptive backoff."""

import asyncio
from dataclasses import FrozenInstanceError
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import BaseMessage, HumanMessage

from myrm_agent_harness.agent.streaming.recovery.turn_retry_state import TurnRetryState
from myrm_agent_harness.agent.streaming.stream_compactor import StreamCompactor
from myrm_agent_harness.agent.streaming.stream_executor import (
    StreamContext,
    StreamExecutor,
)
from myrm_agent_harness.agent.types import AgentRunStatistics
from myrm_agent_harness.toolkits.llms.reliability.jittered_backoff import (
    paas_overload_retry_ceiling,
)


class FakeCompactor:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def put(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        pass


class _FakeError(Exception):
    def __init__(self, msg: str, status_code: int | None = None) -> None:
        super().__init__(msg)
        self.status_code = status_code


@pytest.fixture
def ctx() -> StreamContext:
    stats = AgentRunStatistics()
    return StreamContext(
        agent=MagicMock(),
        agent_input={"messages": [HumanMessage(content="Hello AI, analyze this")]},
        merged_context={"locale": "en"},
        run_config={},
        stats=stats,
        message_id="test_reasoning_recovery",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
    )


def _make_executor(ctx: StreamContext) -> StreamExecutor:
    executor = StreamExecutor(
        ctx=ctx,
        fallback_llm=None,
        safety_fallback_llm=None,
        rebuild_agent_fn=MagicMock(),
    )
    executor._compactor = cast(StreamCompactor, FakeCompactor())
    return executor


class TestTurnRetryStateImmutability:
    def test_frozen_immutability(self) -> None:
        state = TurnRetryState()
        with pytest.raises(FrozenInstanceError):
            state.reasoning_mandatory_attempted = True  # type: ignore[misc]

    def test_with_reasoning_floor(self) -> None:
        state = TurnRetryState()
        evolved = state.with_reasoning_floor(effort="low")
        assert state.reasoning_mandatory_attempted is False
        assert state.reasoning_floor_required is False
        assert state.active_reasoning_effort is None

        assert evolved.reasoning_mandatory_attempted is True
        assert evolved.reasoning_floor_required is True
        assert evolved.active_reasoning_effort == "low"

    def test_with_paas_1305_incremented(self) -> None:
        state = TurnRetryState()
        evolved1 = state.with_paas_1305_incremented()
        evolved2 = evolved1.with_paas_1305_incremented()
        assert state.paas_1305_retries == 0
        assert evolved1.paas_1305_retries == 1
        assert evolved2.paas_1305_retries == 2


class TestReasoningMandatorySelfHealing:
    @pytest.mark.asyncio
    async def test_preserves_messages_and_sets_floor(self, ctx: StreamContext) -> None:
        executor = _make_executor(ctx)
        original_msg = HumanMessage(content="Keep Prompt Cache key strictly aligned")
        assert isinstance(ctx.agent_input, dict)
        ctx.agent_input["messages"] = [original_msg]

        exc = _FakeError(
            "Thinking is mandatory for this model and cannot be disabled.",
            status_code=400,
        )

        recovered = await executor._handle_reasoning_mandatory(exc)
        assert recovered is True

        # Ensure messages are completely untouched to guarantee Prompt Cache byte alignment
        assert isinstance(ctx.agent_input, dict)
        messages = cast(list[BaseMessage], ctx.agent_input["messages"])
        assert len(messages) == 1
        assert messages[0] is original_msg

        # Ensure retry state was updated
        assert ctx.retry_state.reasoning_mandatory_attempted is True
        assert ctx.retry_state.reasoning_floor_required is True
        assert ctx.retry_state.active_reasoning_effort == "low"

        # Calling again should return False (one-shot per turn)
        second_attempt = await executor._handle_reasoning_mandatory(exc)
        assert second_attempt is False

    @pytest.mark.asyncio
    async def test_non_reasoning_mandatory_ignored(self, ctx: StreamContext) -> None:
        executor = _make_executor(ctx)
        exc = _FakeError("Invalid parameter: temperature", status_code=400)

        recovered = await executor._handle_reasoning_mandatory(exc)
        assert recovered is False
        assert ctx.retry_state.reasoning_mandatory_attempted is False


class TestTransientRetryPaas1305:
    @pytest.mark.asyncio
    async def test_paas_1305_increments_retry_state_and_respects_ceiling(
        self, ctx: StreamContext
    ) -> None:
        executor = _make_executor(ctx)
        paas_err = _FakeError(
            "Error code 1305: Engine temporarily overloaded, queue full",
            status_code=429,
        )

        with patch.object(executor, "_sleep_unless_cancelled", return_value=True):
            # Attempt 0 -> should succeed and increment paas_1305_retries to 1
            result = await executor._handle_transient_retry(paas_err, retries=0)
            assert result is True
            assert ctx.retry_state.paas_1305_retries == 1

            # Exceed ceiling -> should return False
            ceiling = paas_overload_retry_ceiling()
            result_exceeded = await executor._handle_transient_retry(paas_err, retries=ceiling)
            assert result_exceeded is False
