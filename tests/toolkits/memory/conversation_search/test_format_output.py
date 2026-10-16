"""Tests for conversation search format output."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.conversation_search.format_output import (
    _format_coverage_notice,
    format_conversation_hit,
    format_conversation_search_response,
)
from myrm_agent_harness.toolkits.memory.conversation_search.types import (
    ConversationIndexCoverage,
    ConversationSearchHit,
    ConversationSearchMode,
    ConversationSearchResponse,
)


def test_format_conversation_hit_includes_message_id() -> None:
    hit = ConversationSearchHit(
        conversation_id="chat-1",
        title="Planning session",
        snippet="Discussed Redis caching.",
        score=0.82,
        message_id="msg-42",
    )

    block = format_conversation_hit(1, hit)

    assert "message_id: msg-42" in block
    assert "conversation_id: chat-1" in block
    assert "Discussed Redis caching." in block


def test_coverage_notice_silent_when_complete() -> None:
    coverage = ConversationIndexCoverage(
        total_conversations=50,
        indexed_conversations=50,
        coverage_ratio=1.0,
        unindexed_recent_count=0,
        indexing_degraded=False,
    )
    notice = _format_coverage_notice(coverage)
    assert notice is None


def test_coverage_notice_silent_when_none() -> None:
    assert _format_coverage_notice(None) is None


def test_coverage_notice_renders_when_partial() -> None:
    coverage = ConversationIndexCoverage(
        total_conversations=100,
        indexed_conversations=50,
        coverage_ratio=0.5,
        unindexed_recent_count=50,
        indexing_degraded=False,
    )
    notice = _format_coverage_notice(coverage)
    assert notice is not None
    assert "50/100" in notice
    assert "50.0%" in notice
    assert "50 sessions pending index" in notice


def test_coverage_notice_renders_when_degraded() -> None:
    coverage = ConversationIndexCoverage(
        total_conversations=100,
        indexed_conversations=100,
        coverage_ratio=1.0,
        unindexed_recent_count=0,
        indexing_degraded=True,
    )
    notice = _format_coverage_notice(coverage)
    assert notice is not None
    assert "degraded" in notice.lower()


async def test_format_conversation_search_response_empty_with_partial_coverage() -> None:
    coverage = ConversationIndexCoverage(
        total_conversations=100,
        indexed_conversations=30,
        coverage_ratio=0.3,
        unindexed_recent_count=70,
        indexing_degraded=False,
    )
    resp = ConversationSearchResponse(
        mode="search",
        hits=[],
        query="docker compose",
        rejected_reason="No sufficiently relevant previous conversations found.",
        coverage=coverage,
    )
    result = await format_conversation_search_response(resp)
    assert isinstance(result, dict)
    body = str(result.get("content", ""))
    assert "30/100" in body
    assert "70 sessions pending index" in body
    assert "No sufficiently relevant previous conversations found." in body


async def test_format_conversation_search_response_with_hits_and_complete_coverage() -> None:
    coverage = ConversationIndexCoverage(
        total_conversations=10,
        indexed_conversations=10,
        coverage_ratio=1.0,
        unindexed_recent_count=0,
        indexing_degraded=False,
    )
    hit = ConversationSearchHit(
        conversation_id="chat-99",
        title="Docker setup",
        snippet="docker compose up -d",
        score=0.9,
    )
    resp = ConversationSearchResponse(
        mode="search",
        hits=[hit],
        query="docker",
        coverage=coverage,
    )
    result = await format_conversation_search_response(resp)
    assert isinstance(result, dict)
    body = str(result.get("content", ""))
    assert "Notice: Conversation search covered" not in body
    assert "Docker setup" in body


def _single_hit_response(
    *, mode: ConversationSearchMode, query: str, hit: ConversationSearchHit
) -> ConversationSearchResponse:
    return ConversationSearchResponse(mode=mode, query=query, hits=[hit])


async def test_format_response_emits_conversation_history_sources() -> None:
    hit = ConversationSearchHit(
        conversation_id="chat-1",
        title="Deployment plan",
        snippet="Use Docker Compose for the local service.",
        summary="The plan preferred local SQLite and embedded Qdrant.",
        score=0.95,
        source="hybrid",
        message_id="msg-1",
    )

    result = await format_conversation_search_response(_single_hit_response(mode="search", query="deployment", hit=hit))

    body = str(result.get("content", ""))
    assert "Deployment plan" in body
    assert "local SQLite" in body
    assert "Docker Compose" in body
    metadata = result.get("metadata", {})
    assert isinstance(metadata, dict)
    assert metadata.get("sources") == [
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


async def test_format_response_recent_mode_lists_recent_conversations() -> None:
    hit = ConversationSearchHit(
        conversation_id="chat-recent",
        title="Recent plan",
        snippet="Recent deployment plan",
        score=0.9,
        source="recent",
    )

    result = await format_conversation_search_response(_single_hit_response(mode="recent", query="", hit=hit))

    assert "Recent conversations:" in str(result.get("content", ""))


async def test_format_response_without_hits_names_indexed_history_on_partial_coverage() -> None:
    coverage = ConversationIndexCoverage(
        total_conversations=20,
        indexed_conversations=15,
        coverage_ratio=0.75,
        unindexed_recent_count=5,
    )

    result = await format_conversation_search_response(
        ConversationSearchResponse(mode="search", query="budget", hits=[], coverage=coverage)
    )

    body = str(result.get("content", ""))
    assert "[Notice: Conversation search covered 15/20 sessions (75.0%); 5 sessions pending index]" in body
    assert "No matching conversations found in indexed history." in body


async def test_format_response_without_hits_stays_quiet_on_full_coverage() -> None:
    coverage = ConversationIndexCoverage(
        total_conversations=20,
        indexed_conversations=20,
        coverage_ratio=1.0,
        unindexed_recent_count=0,
    )

    result = await format_conversation_search_response(
        ConversationSearchResponse(mode="search", query="budget", hits=[], coverage=coverage)
    )

    body = str(result.get("content", ""))
    assert "[Notice:" not in body
    assert "No matching conversations found." in body


async def test_format_response_without_hits_reports_degraded_index() -> None:
    coverage = ConversationIndexCoverage(
        total_conversations=10,
        indexed_conversations=0,
        coverage_ratio=0.0,
        unindexed_recent_count=10,
        indexing_degraded=True,
    )

    result = await format_conversation_search_response(
        ConversationSearchResponse(mode="search", query="budget", hits=[], coverage=coverage)
    )

    assert "[Notice: Conversation index is currently rebuilding or degraded; coverage may be partial]" in str(
        result.get("content", "")
    )


async def test_format_response_expanded_view_keeps_long_snippet_and_drops_the_tip() -> None:
    long_content = "Step " + ("x" * 2000) + " end of detailed context"
    hit = ConversationSearchHit(
        conversation_id="chat-1",
        title="Deployment plan",
        snippet=long_content,
        score=1.0,
        source="conversation_index",
        message_id="msg-1",
    )

    result = await format_conversation_search_response(_single_hit_response(mode="search", query="", hit=hit))

    body = str(result.get("content", ""))
    assert "end of detailed context" in body
    assert len(body) > 1500
    assert "tip: pass expand_conversation_id=" not in body


async def test_format_response_recent_hit_is_bounded_and_offers_the_expand_tip() -> None:
    hit = ConversationSearchHit(
        conversation_id="chat-recent",
        title="Recent only",
        snippet="A" * 1500,
        score=1.0,
        source="recent",
        message_id="msg-recent",
    )

    result = await format_conversation_search_response(_single_hit_response(mode="recent", query="", hit=hit))

    body = str(result.get("content", ""))
    assert "A" * 700 in body
    assert "A" * 701 not in body
    assert len(body) < 1200
    assert "tip: pass expand_conversation_id='chat-recent'" in body
