"""Streamed summary text is assembled from text content, whatever shape the provider streams it in.

Providers that stream content blocks (``[{"type": "text", ...}]``) used to make the chunk join fail,
and the failure was swallowed by the ``ainvoke`` fallback: the whole summary was generated twice.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage

from myrm_agent_harness.agent.context_management.strategies.summary.progress_timeout import ProgressClock
from myrm_agent_harness.agent.context_management.strategies.summary.summarizer import _stream_with_progress


class _StreamingModel:
    """Chat-model double: ``astream`` yields the given chunks; ``ainvoke`` records fallback calls."""

    def __init__(self, chunks: list[AIMessageChunk]) -> None:
        self._chunks = chunks
        self.ainvoke_calls = 0

    def astream(self, messages: list[BaseMessage]) -> AsyncIterator[AIMessageChunk]:
        async def generate() -> AsyncIterator[AIMessageChunk]:
            for chunk in self._chunks:
                yield chunk

        return generate()

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.ainvoke_calls += 1
        return AIMessage(content="fallback")


def _text(value: str) -> dict[str, str]:
    return {"type": "text", "text": value}


@pytest.mark.parametrize(
    "chunks",
    [
        pytest.param([AIMessageChunk(content="hel"), AIMessageChunk(content="lo")], id="string-content"),
        pytest.param(
            [AIMessageChunk(content=[_text("hel")]), AIMessageChunk(content=[_text("lo")])],
            id="text-blocks",
        ),
        pytest.param(
            [
                AIMessageChunk(content=[{"type": "thinking", "thinking": "hm"}]),
                AIMessageChunk(content=[_text("hel")]),
                AIMessageChunk(content="lo"),
            ],
            id="thinking-blocks-are-not-summary-text",
        ),
    ],
)
async def test_streamed_text_is_joined_without_a_second_call(chunks: list[AIMessageChunk]) -> None:
    model = _StreamingModel(chunks)

    message = await _stream_with_progress(cast("BaseChatModel", model), [], ProgressClock())

    assert message.content == "hello"
    assert model.ainvoke_calls == 0
