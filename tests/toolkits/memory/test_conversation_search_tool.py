from __future__ import annotations

import pytest
from pydantic import ValidationError

from myrm_agent_harness.toolkits.memory.conversation_search import (
    ConversationSearchHit,
    ConversationSearchInput,
    ConversationSearchRequest,
    ConversationSearchResponse,
    create_conversation_search_tool,
)
from myrm_agent_harness.utils.runtime.progress_sink import set_tool_progress_sink


class FakeConversationSearchProvider:
    def __init__(self) -> None:
        self.requests: list[ConversationSearchRequest] = []

    async def search(self, request: ConversationSearchRequest) -> ConversationSearchResponse:
        self.requests.append(request)
        if not request.query:
            return ConversationSearchResponse(
                mode="recent",
                hits=[
                    ConversationSearchHit(
                        conversation_id="chat-recent",
                        title="Recent plan",
                        snippet="Recent deployment plan",
                        summary="We discussed a local Tauri deployment.",
                        score=0.9,
                        source="recent",
                    )
                ],
            )
        return ConversationSearchResponse(
            mode="search",
            query=request.query,
            hits=[
                ConversationSearchHit(
                    conversation_id="chat-1",
                    title="Deployment plan",
                    snippet="Use Docker Compose for the local service.",
                    summary="The plan preferred local SQLite and embedded Qdrant.",
                    score=0.95,
                    source="hybrid",
                    message_id="msg-1",
                )
            ],
        )


class CapturingSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def emit(self, event: dict[str, object]) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_conversation_search_tool_formats_search_results() -> None:
    provider = FakeConversationSearchProvider()
    search_tool = create_conversation_search_tool(provider)

    result = await search_tool.ainvoke({"query": "deployment", "limit": 3})

    assert search_tool.name == "conversation_search_tool"
    assert "Deployment plan" in result
    assert "local SQLite" in result
    assert "Docker Compose" in result
    assert provider.requests[0].query == "deployment"
    assert provider.requests[0].limit == 3


@pytest.mark.asyncio
async def test_conversation_search_tool_emits_sources_not_memory_citations() -> None:
    provider = FakeConversationSearchProvider()
    search_tool = create_conversation_search_tool(provider)
    sink = CapturingSink()
    set_tool_progress_sink(sink)

    try:
        await search_tool.ainvoke({"query": "deployment"})
    finally:
        set_tool_progress_sink(None)

    assert sink.events == [
        {
            "type": "sources",
            "data": [
                {
                    "type": "conversation_history",
                    "conversation_id": "chat-1",
                    "message_id": "msg-1",
                    "title": "Deployment plan",
                    "snippet": "Use Docker Compose for the local service.",
                    "summary": "The plan preferred local SQLite and embedded Qdrant.",
                    "score": 0.95,
                    "index": 1,
                    "source_key": "conversation:chat-1:msg-1",
                }
            ],
        }
    ]


@pytest.mark.asyncio
async def test_conversation_search_tool_routes_star_to_recent() -> None:
    provider = FakeConversationSearchProvider()
    search_tool = create_conversation_search_tool(provider)

    result = await search_tool.ainvoke({"query": "*"})

    assert "Recent conversations" in result
    assert provider.requests[0].query == ""


@pytest.mark.asyncio
async def test_conversation_search_tool_normalizes_none_query_to_recent() -> None:
    provider = FakeConversationSearchProvider()
    search_tool = create_conversation_search_tool(provider)

    result = await search_tool.ainvoke({"query": None})

    assert "Recent conversations" in result
    assert provider.requests[0].query == ""


def test_conversation_search_input_rejects_unsupported_scope() -> None:
    with pytest.raises(ValidationError):
        ConversationSearchInput(query="deployment", scope="all")


def test_conversation_search_input_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ConversationSearchInput(query="deployment", tenant_id="hallucinated")
