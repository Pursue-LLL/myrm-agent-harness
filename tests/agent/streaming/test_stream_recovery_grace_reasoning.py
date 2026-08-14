"""Tests for StreamRecoveryMixin._grace_call_summary reasoning-model fallback."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.streaming.stream_executor import (
    StreamContext,
    StreamExecutor,
)
from myrm_agent_harness.agent.types import AgentRunStatistics


class _FakeCompactor:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def put(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        pass


def _make_ctx(llm: object | None) -> StreamContext:
    return StreamContext(
        agent=MagicMock(),
        agent_input={"messages": [HumanMessage(content="test")]},
        merged_context={"locale": "en"},
        run_config={},
        stats=AgentRunStatistics(),
        message_id="grace_test",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
        llm=llm,
    )


def _make_executor(ctx: StreamContext) -> StreamExecutor:
    executor = StreamExecutor(
        ctx=ctx,
        fallback_llm=None,
        safety_fallback_llm=None,
        rebuild_agent_fn=MagicMock(),
    )
    executor._compactor = _FakeCompactor()
    return executor


class TestGraceCallSummaryReasoningModel:
    @pytest.mark.asyncio
    async def test_reasoning_model_content_empty_falls_back(self) -> None:
        """Grace summary must use reasoning_content when content is empty."""
        llm = MagicMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(
                content="",
                additional_kwargs={"reasoning_content": "Found MCP results: login works."},
            )
        )
        executor = _make_executor(_make_ctx(llm))
        with patch.object(executor, "_emit_message_pair", new_callable=AsyncMock) as emit:
            await executor._grace_call_summary([HumanMessage(content="q"), AIMessage(content="doing work")])
        emitted = emit.call_args[0][0]
        assert "login works" in emitted
        assert "maximum iteration" not in emitted

    @pytest.mark.asyncio
    async def test_empty_response_uses_fallback_text(self) -> None:
        """Fully empty response must fall back to the generic grace message."""
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="", additional_kwargs={}))
        executor = _make_executor(_make_ctx(llm))
        with patch.object(executor, "_emit_message_pair", new_callable=AsyncMock) as emit:
            await executor._grace_call_summary([HumanMessage(content="q"), AIMessage(content="doing work")])
        emitted = emit.call_args[0][0]
        assert "iteration limit" in emitted
