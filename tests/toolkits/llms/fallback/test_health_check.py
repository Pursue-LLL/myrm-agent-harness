"""Tests for the liveness probe: a deadline that really applies, a request left unaltered, and classified failures."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage
from litellm.types.utils import Choices, Message, ModelResponse

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.fallback.health_check import (
    lightweight_health_check,
    probe_llm_health,
)


async def test_answering_model_is_healthy_and_gets_a_plain_request() -> None:
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="response")

    assert await lightweight_health_check(llm) is True

    llm.ainvoke.assert_awaited_once()
    (messages,), kwargs = llm.ainvoke.await_args
    assert [type(m) for m in messages] == [HumanMessage]
    # Nothing is passed that the model would silently ignore (a RunnableConfig does not carry token or time limits).
    assert kwargs == {}


async def test_empty_response_is_unhealthy() -> None:
    llm = AsyncMock()
    llm.ainvoke.return_value = None

    assert await lightweight_health_check(llm) is False


async def test_provider_error_is_unhealthy() -> None:
    llm = AsyncMock()
    llm.ainvoke.side_effect = RuntimeError("connection failed")

    assert await lightweight_health_check(llm) is False


async def test_provider_side_timeout_is_unhealthy() -> None:
    llm = AsyncMock()
    llm.ainvoke.side_effect = TimeoutError("timed out")

    assert await lightweight_health_check(llm) is False


async def test_hung_model_is_cancelled_at_the_deadline() -> None:
    cancelled = asyncio.Event()

    async def hang(*_: object, **__: object) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    llm = MagicMock()
    llm.ainvoke = hang

    started = time.monotonic()
    result = await lightweight_health_check(llm, timeout_s=0.05)

    assert result is False
    assert time.monotonic() - started < 2.0
    assert cancelled.is_set()


async def test_deadline_applies_to_a_real_model_whose_provider_never_answers() -> None:
    model = ChatLiteLLM(model="openai/probe-model", max_tokens=4096)
    model.client = MagicMock()

    async def never_answers(**_: object) -> None:
        await asyncio.Event().wait()

    model.client.acreate = AsyncMock(side_effect=never_answers)

    started = time.monotonic()
    assert await lightweight_health_check(model, timeout_s=0.1) is False
    assert time.monotonic() - started < 2.0


async def test_probe_leaves_the_models_token_budget_alone() -> None:
    model = ChatLiteLLM(model="openai/probe-model", max_tokens=4096)
    model.client = MagicMock()
    model.client.acreate = AsyncMock(
        return_value=ModelResponse(
            choices=[Choices(message=Message(role="assistant", content="ok"), finish_reason="stop")]
        )
    )

    assert await lightweight_health_check(model) is True

    assert model.client.acreate.call_args.kwargs["max_tokens"] == 4096


async def test_probe_reports_a_healthy_model_with_its_latency() -> None:
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="response")

    result = await probe_llm_health(llm)

    assert result.ok is True
    assert result.error_kind == "none"
    assert result.error is None
    assert result.latency_ms is not None


async def test_probe_classifies_a_deadline_miss_as_timeout() -> None:
    async def hang(*_: object, **__: object) -> None:
        await asyncio.Event().wait()

    llm = MagicMock()
    llm.ainvoke = hang

    result = await probe_llm_health(llm, timeout_s=0.05)

    assert result.ok is False
    assert result.error_kind == "timeout"
    assert result.error is not None and "0.05" in result.error


async def test_probe_keeps_the_provider_reason_and_labels_it_as_provider_error() -> None:
    llm = AsyncMock()
    llm.ainvoke.side_effect = RuntimeError("Invalid credential")

    result = await probe_llm_health(llm)

    assert result.ok is False
    assert result.error_kind == "provider_error"
    assert result.error is not None
    assert "RuntimeError" in result.error
    assert "Invalid credential" in result.error


async def test_probe_does_not_mistake_a_provider_timeout_for_our_deadline() -> None:
    llm = AsyncMock()
    llm.ainvoke.side_effect = TimeoutError("upstream read timeout")

    result = await probe_llm_health(llm, timeout_s=30.0)

    assert result.ok is False
    assert result.error_kind == "provider_error"
    assert result.error is not None and "upstream read timeout" in result.error


async def test_probe_classifies_an_empty_answer_as_provider_error() -> None:
    llm = AsyncMock()
    llm.ainvoke.return_value = None

    result = await probe_llm_health(llm)

    assert result.ok is False
    assert result.error_kind == "provider_error"
    assert result.error is not None and "empty" in result.error.lower()
