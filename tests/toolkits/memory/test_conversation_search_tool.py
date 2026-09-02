from __future__ import annotations

import pytest
from pydantic import ValidationError

from myrm_agent_harness.toolkits.memory.conversation_search import (
    CONVERSATION_SEARCH_TOOL_NAME,
    ConversationIndexCoverage,
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

    assert isinstance(result, dict)
    content = str(result.get("content", ""))
    assert search_tool.name == "conversation_search_tool"
    assert "Deployment plan" in content
    assert "local SQLite" in content
    assert "Docker Compose" in content
    assert provider.requests[0].query == "deployment"
    assert provider.requests[0].limit == 3


@pytest.mark.asyncio
async def test_conversation_search_tool_emits_sources_not_memory_citations() -> None:
    provider = FakeConversationSearchProvider()
    search_tool = create_conversation_search_tool(provider)

    result = await search_tool.ainvoke({"query": "deployment"})

    assert isinstance(result, dict)
    metadata = result.get("metadata", {})
    assert isinstance(metadata, dict)
    sources = metadata.get("sources")
    assert sources == [
        {
            "type": "conversation_history",
            "conversation_id": "chat-1",
            "message_id": "msg-1",
            "title": "Deployment plan",
            "snippet": "Use Docker Compose for the local service.",
            "summary": "The plan preferred local SQLite and embedded Qdrant.",
            "score": 0.95,
            "source_key": "conversation:chat-1:msg-1",
        }
    ]


@pytest.mark.asyncio
async def test_conversation_search_tool_routes_star_to_recent() -> None:
    provider = FakeConversationSearchProvider()
    search_tool = create_conversation_search_tool(provider)

    result = await search_tool.ainvoke({"query": "*"})

    assert isinstance(result, dict)
    content = str(result.get("content", ""))
    assert "Recent conversations" in content
    assert provider.requests[0].query == ""


@pytest.mark.asyncio
async def test_conversation_search_tool_normalizes_none_query_to_recent() -> None:
    provider = FakeConversationSearchProvider()
    search_tool = create_conversation_search_tool(provider)

    result = await search_tool.ainvoke({"query": None})

    assert isinstance(result, dict)
    content = str(result.get("content", ""))
    assert "Recent conversations" in content
    assert provider.requests[0].query == ""


def test_conversation_search_input_rejects_unsupported_scope() -> None:
    with pytest.raises(ValidationError):
        ConversationSearchInput(query="deployment", scope="all")


def test_conversation_search_input_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ConversationSearchInput(query="deployment", tenant_id="hallucinated")


@pytest.mark.asyncio
async def test_conversation_search_tool_with_partial_coverage_notice() -> None:
    class PartialCoverageProvider:
        async def search(self, request: ConversationSearchRequest) -> ConversationSearchResponse:
            return ConversationSearchResponse(
                mode="search",
                query=request.query,
                hits=[],
                coverage=ConversationIndexCoverage(
                    total_conversations=20,
                    indexed_conversations=15,
                    coverage_ratio=0.75,
                    unindexed_recent_count=5,
                ),
            )

    provider = PartialCoverageProvider()
    search_tool = create_conversation_search_tool(provider)
    result = await search_tool.ainvoke({"query": "budget"})

    assert isinstance(result, dict)
    content = str(result.get("content", ""))
    assert "[Notice: Conversation search covered 15/20 sessions (75.0%); 5 sessions pending index]" in content
    assert "No matching conversations found in indexed history." in content


@pytest.mark.asyncio
async def test_conversation_search_tool_with_full_coverage_quiet() -> None:
    class FullCoverageProvider:
        async def search(self, request: ConversationSearchRequest) -> ConversationSearchResponse:
            return ConversationSearchResponse(
                mode="search",
                query=request.query,
                hits=[],
                coverage=ConversationIndexCoverage(
                    total_conversations=20,
                    indexed_conversations=20,
                    coverage_ratio=1.0,
                    unindexed_recent_count=0,
                ),
            )

    provider = FullCoverageProvider()
    search_tool = create_conversation_search_tool(provider)
    result = await search_tool.ainvoke({"query": "budget"})

    assert isinstance(result, dict)
    content = str(result.get("content", ""))
    assert "[Notice:" not in content
    assert "No matching conversations found." in content


@pytest.mark.asyncio
async def test_conversation_search_tool_with_degraded_index_notice() -> None:
    class DegradedProvider:
        async def search(self, request: ConversationSearchRequest) -> ConversationSearchResponse:
            return ConversationSearchResponse(
                mode="search",
                query=request.query,
                hits=[],
                coverage=ConversationIndexCoverage(
                    total_conversations=10,
                    indexed_conversations=0,
                    coverage_ratio=0.0,
                    unindexed_recent_count=10,
                    indexing_degraded=True,
                ),
            )

    provider = DegradedProvider()
    search_tool = create_conversation_search_tool(provider)
    result = await search_tool.ainvoke({"query": "budget"})

    assert isinstance(result, dict)
    content = str(result.get("content", ""))
    assert "[Notice: Conversation index is currently rebuilding or degraded; coverage may be partial]" in content
