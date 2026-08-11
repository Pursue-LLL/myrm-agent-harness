"""Unit tests for non-streaming LLM token usage recording in ChatLiteLLM.

Verifies that sync ``_generate`` and async ``_agenerate`` non-streaming paths
record token usage + finish reason into the request-scoped TokenTracker,
closing the gap where only streaming calls were accounted.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.chat_model_exceptions import (
    EmptyChoicesError,
)
from myrm_agent_harness.utils.token_economics.tracker import (
    get_pending_token_events,
    get_token_tracker,
    init_token_tracker,
    reset_token_tracker,
)


def _make_response(
    *, include_usage: bool = True, finish_reason: str = "stop"
) -> dict[str, Any]:
    resp: dict[str, Any] = {
        "id": "chatcmpl-ns-1",
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": "Hello"},
            }
        ],
    }
    if include_usage:
        resp["usage"] = {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
    return resp


@pytest.fixture(autouse=True)
def _reset_tracker() -> Iterator[None]:
    init_token_tracker()
    yield
    reset_token_tracker()


class TestSyncNonStreamUsage:
    def test_generate_records_token_usage(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        model.client.completion.return_value = _make_response()

        result = model._generate([HumanMessage(content="hi")])

        assert len(result.generations) == 1
        events = get_pending_token_events()
        assert len(events) == 1
        usage = cast(dict[str, object], events[0]["usage"])
        assert usage["prompt_tokens"] == 10
        assert usage["completion_tokens"] == 5
        assert usage["total_tokens"] == 15

    def test_generate_records_finish_reason(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        model.client.completion.return_value = _make_response()

        model._generate([HumanMessage(content="hi")])

        tracker = get_token_tracker()
        assert tracker is not None
        assert tracker.last_finish_reason == "stop"

    def test_generate_skips_record_when_usage_missing(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        model.client.completion.return_value = _make_response(include_usage=False)

        result = model._generate([HumanMessage(content="hi")])

        assert len(result.generations) == 1
        assert get_pending_token_events() == []

    def test_generate_skips_record_on_empty_choices(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        model.client.completion.return_value = _make_response()
        model.empty_retry_max_attempts = 1
        monkeypatch.setattr(
            model, "_create_chat_result", MagicMock(side_effect=EmptyChoicesError())
        )

        with pytest.raises(EmptyChoicesError):
            model._generate([HumanMessage(content="hi")])

        assert get_pending_token_events() == []


class TestAsyncNonStreamUsage:
    @pytest.mark.asyncio
    async def test_agenerate_records_token_usage_and_finish_reason(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        model.client.acreate = AsyncMock(return_value=_make_response())

        result = await model._agenerate([HumanMessage(content="hi")])

        assert len(result.generations) == 1
        events = get_pending_token_events()
        assert len(events) == 1
        usage = cast(dict[str, object], events[0]["usage"])
        assert usage["prompt_tokens"] == 10
        assert usage["total_tokens"] == 15
        tracker = get_token_tracker()
        assert tracker is not None
        assert tracker.last_finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_agenerate_skips_record_when_usage_missing(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        model.client.acreate = AsyncMock(
            return_value=_make_response(include_usage=False)
        )

        result = await model._agenerate([HumanMessage(content="hi")])

        assert len(result.generations) == 1
        assert get_pending_token_events() == []

    @pytest.mark.asyncio
    async def test_agenerate_skips_record_on_empty_choices(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        model.client.acreate = AsyncMock(return_value=_make_response())
        model.empty_retry_max_attempts = 1
        monkeypatch.setattr(
            model, "_create_chat_result", MagicMock(side_effect=EmptyChoicesError())
        )

        with pytest.raises(EmptyChoicesError):
            await model._agenerate([HumanMessage(content="hi")])

        assert get_pending_token_events() == []
