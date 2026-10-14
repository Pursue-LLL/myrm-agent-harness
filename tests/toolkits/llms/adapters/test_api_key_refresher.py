"""API key refresher: a host-registered hook that renews an expiring key before each async LLM request."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.chat_model.api_key_refresher import (
    renew_api_key,
    set_api_key_refresher,
)


@pytest.fixture(autouse=True)
def _no_refresher() -> Iterator[None]:
    set_api_key_refresher(None)
    yield
    set_api_key_refresher(None)


def _renewing(mapping: dict[str, str | None]) -> AsyncMock:
    async def refresher(current: str) -> str | None:
        return mapping.get(current)

    return AsyncMock(side_effect=refresher)


def _response() -> dict[str, object]:
    return {
        "id": "chatcmpl-1",
        "model": "test-model",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class _Chunk:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def model_dump(self) -> dict[str, Any]:
        return self._data


async def _stream() -> AsyncIterator[_Chunk]:
    for data in (
        {"choices": [{"delta": {"role": "assistant", "content": "ok"}}]},
        {"choices": [{"delta": {"content": None}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
    ):
        yield _Chunk(data)


def _model(**fields: Any) -> ChatLiteLLM:
    model = ChatLiteLLM(model="xai/grok-4", api_base="https://api.x.ai/v1", **fields)
    model.client = MagicMock()
    model.client.acreate = AsyncMock(return_value=_response())
    return model


class TestRegistry:
    @pytest.mark.asyncio
    async def test_without_a_refresher_nothing_is_renewed(self) -> None:
        assert await renew_api_key("key") is None

    @pytest.mark.asyncio
    async def test_returns_the_renewed_key(self) -> None:
        refresher = _renewing({"old": "new"})
        set_api_key_refresher(refresher)

        assert await renew_api_key("old") == "new"
        refresher.assert_awaited_once_with("old")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("answer", [None, "", "same"])
    async def test_no_change_means_keep_the_current_key(self, answer: str | None) -> None:
        set_api_key_refresher(_renewing({"same": answer}))

        assert await renew_api_key("same") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current", [None, ""])
    async def test_a_missing_key_never_reaches_the_refresher(self, current: str | None) -> None:
        refresher = _renewing({})
        set_api_key_refresher(refresher)

        assert await renew_api_key(current) is None
        refresher.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_failing_refresher_keeps_the_key_and_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        set_api_key_refresher(AsyncMock(side_effect=RuntimeError("token store down")))

        with caplog.at_level(logging.WARNING):
            assert await renew_api_key("old") is None

        assert "API key refresher failed" in caplog.text

    @pytest.mark.asyncio
    async def test_cancellation_is_not_swallowed(self) -> None:
        set_api_key_refresher(AsyncMock(side_effect=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await renew_api_key("old")

    @pytest.mark.asyncio
    async def test_registering_none_removes_the_refresher(self) -> None:
        refresher = _renewing({"old": "new"})
        set_api_key_refresher(refresher)
        set_api_key_refresher(None)

        assert await renew_api_key("old") is None
        refresher.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_public_hooks_facade_registers_into_the_same_registry(self) -> None:
        from myrm_agent_harness.api.hooks import set_api_key_refresher as register_through_facade

        refresher = _renewing({"old": "new"})
        register_through_facade(refresher)

        assert await renew_api_key("old") == "new"


class TestChatModelRequests:
    @pytest.mark.asyncio
    async def test_non_streaming_request_carries_the_renewed_key_everywhere(self) -> None:
        model = _model(api_key="old")
        refresher = _renewing({"old": "new"})
        set_api_key_refresher(refresher)

        await model.ainvoke([HumanMessage(content="hi")])

        sent = model.client.acreate.call_args.kwargs
        assert sent["api_key"] == "new"
        assert sent["extra_headers"]["Authorization"] == "Bearer new"
        assert model.api_key == "new"
        refresher.assert_awaited_once_with("old")

    @pytest.mark.asyncio
    async def test_renewal_is_asked_again_with_the_adopted_key_on_the_next_request(self) -> None:
        model = _model(api_key="old")
        refresher = _renewing({"old": "new"})
        set_api_key_refresher(refresher)

        await model.ainvoke([HumanMessage(content="first")])
        await model.ainvoke([HumanMessage(content="second")])

        assert [call.args[0] for call in refresher.await_args_list] == ["old", "new"]
        assert model.client.acreate.call_args.kwargs["api_key"] == "new"

    @pytest.mark.asyncio
    async def test_key_held_only_as_openai_api_key_is_renewed_too(self) -> None:
        model = _model(openai_api_key="old")
        set_api_key_refresher(_renewing({"old": "new"}))

        await model.ainvoke([HumanMessage(content="hi")])

        assert model.client.acreate.call_args.kwargs["api_key"] == "new"

    @pytest.mark.asyncio
    async def test_without_a_refresher_the_key_is_untouched(self) -> None:
        model = _model(api_key="old")

        await model.ainvoke([HumanMessage(content="hi")])

        assert model.client.acreate.call_args.kwargs["api_key"] == "old"

    @pytest.mark.asyncio
    async def test_a_failing_refresher_does_not_fail_the_request(self) -> None:
        model = _model(api_key="old")
        set_api_key_refresher(AsyncMock(side_effect=RuntimeError("token store down")))

        result = await model.ainvoke([HumanMessage(content="hi")])

        assert result.content == "ok"
        assert model.client.acreate.call_args.kwargs["api_key"] == "old"

    @pytest.mark.asyncio
    async def test_streaming_request_carries_the_renewed_key_and_asks_once(self) -> None:
        model = _model(api_key="old")
        model.client.acreate = AsyncMock(return_value=_stream())
        refresher = _renewing({"old": "new"})
        set_api_key_refresher(refresher)

        chunks = [chunk async for chunk in model.astream([HumanMessage(content="hi")])]

        assert chunks
        assert model.client.acreate.call_args.kwargs["api_key"] == "new"
        refresher.assert_awaited_once_with("old")

    @pytest.mark.asyncio
    async def test_streamed_generate_asks_once_not_per_layer(self) -> None:
        model = _model(api_key="old", streaming=True)
        model.client.acreate = AsyncMock(return_value=_stream())
        refresher = _renewing({"old": "new"})
        set_api_key_refresher(refresher)

        await model.ainvoke([HumanMessage(content="hi")])

        assert model.client.acreate.call_args.kwargs["api_key"] == "new"
        refresher.assert_awaited_once_with("old")
