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

