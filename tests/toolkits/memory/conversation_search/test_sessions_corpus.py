"""`search_sessions_corpus` maps `memory_search_tool(corpus=sessions)` arguments onto the provider request."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution import (
    search_sessions_corpus,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
    MemorySearchBackends,
)
from myrm_agent_harness.toolkits.memory.conversation_search.types import (
    MAX_CONVERSATION_SEARCH_LIMIT,
    ConversationSearchHit,
    ConversationSearchRequest,
    ConversationSearchResponse,
)


class _RecordingProvider:
    """Conversation provider double that records every request it receives."""

    def __init__(self, response: ConversationSearchResponse) -> None:
        self._response = response
        self.requests: list[ConversationSearchRequest] = []

    async def search(self, request: ConversationSearchRequest) -> ConversationSearchResponse:
        self.requests.append(request)
        return self._response


def _recent_response() -> ConversationSearchResponse:
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


def _empty_search_response() -> ConversationSearchResponse:
    return ConversationSearchResponse(mode="search", query="deployment", hits=[])


async def _search(
    provider: _RecordingProvider,
    *,
    query: str,
    limit: int = 5,
    expand_conversation_id: str | None = None,
    expand_message_id: str | None = None,
    expand_window: int = 5,
) -> str | dict[str, object]:
    return await search_sessions_corpus(
        MemorySearchBackends(conversation_provider=provider),
        query=query,
        limit=limit,
        since=None,
        until=None,
        expand_conversation_id=expand_conversation_id,
        expand_message_id=expand_message_id,
        expand_window=expand_window,
    )


async def test_star_query_routes_to_recent_mode() -> None:
    provider = _RecordingProvider(_recent_response())

    result = await _search(provider, query="*")

    assert isinstance(result, dict)
    assert "Recent conversations" in str(result.get("content", ""))
    assert provider.requests[0].query == ""
    assert provider.requests[0].mode == "recent"


async def test_blank_query_routes_to_recent_mode() -> None:
    provider = _RecordingProvider(_recent_response())

    await _search(provider, query="   ")

    assert provider.requests[0].query == ""
    assert provider.requests[0].mode == "recent"


async def test_text_query_stays_in_search_mode_and_clamps_the_limit() -> None:
    provider = _RecordingProvider(_empty_search_response())

    await _search(provider, query="deployment", limit=500)

    request = provider.requests[0]
    assert request.query == "deployment"
    assert request.mode is None
    assert request.limit == MAX_CONVERSATION_SEARCH_LIMIT
    assert request.scope == "current_agent"


async def test_expand_arguments_are_forwarded_to_the_provider() -> None:
    provider = _RecordingProvider(_empty_search_response())

    await _search(
        provider,
        query="",
        expand_conversation_id="chat-2",
        expand_message_id="msg-2",
        expand_window=8,
    )

    request = provider.requests[0]
    assert request.expand_conversation_id == "chat-2"
    assert request.expand_message_id == "msg-2"
    assert request.expand_window == 8


async def test_missing_provider_reports_unavailable() -> None:
    result = await search_sessions_corpus(
        MemorySearchBackends(),
        query="deployment",
        limit=5,
        since=None,
        until=None,
    )

    assert result == "Conversation history search is not available."
