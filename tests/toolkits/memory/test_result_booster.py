"""Unit tests for ResultBooster (MemPalace enhancement)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.query_analyzer import QueryContext
from myrm_agent_harness.toolkits.memory.result_booster import boost_results
from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemorySearchResult, MemoryType


@pytest.fixture
def retrieval_config():
    """Create default RetrievalConfig for testing."""
    return RetrievalConfig(
        enable_keyword_boost=True,
        keyword_boost_weight=0.30,
        enable_temporal_boost=True,
        temporal_boost_max_weight=0.40,
        enable_person_name_boost=True,
        person_name_boost_weight=0.20,
        enable_quoted_phrase_boost=True,
        quoted_phrase_boost_weight=0.25,
    )


def create_mock_result(content: str, score: float, created_at: datetime | None = None) -> MemorySearchResult:
    """Helper to create mock MemorySearchResult."""
    memory = ConversationMemory(
        id="test_id",
        content=content,
        summary="",
        raw_exchange='{"user": "test", "assistant": "test"}',
        created_at=created_at or datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    return MemorySearchResult(memory=memory, score=score, memory_type=MemoryType.CONVERSATION)


def test_boost_empty_results(retrieval_config):
    """Test boosting empty result list returns empty list."""
    query_context = QueryContext(quoted_phrases=["test"], person_names=[], reference_time=None, temporal_markers=[])

    results = boost_results([], "test query", query_context, retrieval_config)
    assert len(results) == 0


def test_keyword_boost_increases_score(retrieval_config):
    """Test keyword boost increases scores for matching results."""
    results = [
        create_mock_result("This is a test phrase", 0.80),
        create_mock_result("No match here", 0.75),
    ]

    query_context = QueryContext(
        quoted_phrases=["test phrase"], person_names=[], reference_time=None, temporal_markers=[]
    )

    with patch("myrm_agent_harness.toolkits.memory.metrics.get_search_metrics") as mock_metrics:
        mock_metrics_instance = MagicMock()
        mock_metrics.return_value = mock_metrics_instance

        boosted = boost_results(results, 'Find "test phrase"', query_context, retrieval_config)

        assert boosted[0].score > results[0].score
        assert boosted[1].score == results[1].score
        mock_metrics_instance.record_keyword_boost.assert_called_once()
        assert mock_metrics_instance.record_keyword_boost.call_args[0][0] == 1


def test_temporal_boost_recent_results(retrieval_config):
    """Test temporal boost prioritizes recent results."""
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    last_week = now - timedelta(days=7)

    results = [
        create_mock_result("Recent conversation", 0.75, created_at=yesterday),
        create_mock_result("Old conversation", 0.80, created_at=last_week),
    ]

    query_context = QueryContext(quoted_phrases=[], person_names=[], reference_time=now, temporal_markers=["yesterday"])

    with patch("myrm_agent_harness.toolkits.memory.metrics.get_search_metrics") as mock_metrics:
        mock_metrics_instance = MagicMock()
        mock_metrics.return_value = mock_metrics_instance

        boosted = boost_results(results, "What did we discuss yesterday?", query_context, retrieval_config)

        assert boosted[0].content == "Recent conversation"
        assert boosted[0].score > results[0].score
        mock_metrics_instance.record_temporal_boost.assert_called_once()
        assert mock_metrics_instance.record_temporal_boost.call_args[0][0] >= 1


def test_person_name_boost(retrieval_config):
    """Test person name boost increases scores for mentions."""
    results = [
        create_mock_result("Alice suggested this approach", 0.75),
        create_mock_result("No person mentioned", 0.78),
    ]

    query_context = QueryContext(quoted_phrases=[], person_names=["Alice"], reference_time=None, temporal_markers=[])

    with patch("myrm_agent_harness.toolkits.memory.metrics.get_search_metrics"):
        boosted = boost_results(results, "What did Alice say?", query_context, retrieval_config)

        assert boosted[0].content == "Alice suggested this approach"
        assert boosted[0].score > results[0].score


def test_quoted_phrase_boost(retrieval_config):
    """Test quoted phrase boost prioritizes exact matches."""
    results = [
        create_mock_result("The quick brown fox jumps over", 0.75),
        create_mock_result("Something about foxes", 0.78),
    ]

    query_context = QueryContext(
        quoted_phrases=["quick brown fox"], person_names=[], reference_time=None, temporal_markers=[]
    )

    with patch("myrm_agent_harness.toolkits.memory.metrics.get_search_metrics"):
        boosted = boost_results(results, 'Find "quick brown fox"', query_context, retrieval_config)

        assert boosted[0].content == "The quick brown fox jumps over"
        assert boosted[0].score > results[0].score


def test_combined_boosts(retrieval_config):
    """Test multiple boosts can be applied together."""
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)

    results = [
        create_mock_result("Alice mentioned test phrase yesterday", 0.70, created_at=yesterday),
        create_mock_result("Unrelated content", 0.85, created_at=now - timedelta(days=30)),
    ]

    query_context = QueryContext(
        quoted_phrases=["test phrase"], person_names=["Alice"], reference_time=now, temporal_markers=["yesterday"]
    )

    with patch("myrm_agent_harness.toolkits.memory.metrics.get_search_metrics") as mock_metrics:
        mock_metrics_instance = MagicMock()
        mock_metrics.return_value = mock_metrics_instance

        boosted = boost_results(
            results, 'What did Alice say about "test phrase" yesterday?', query_context, retrieval_config
        )

        assert boosted[0].content == "Alice mentioned test phrase yesterday"
        assert boosted[0].score > results[0].score
        original_score = 0.70
        assert boosted[0].score > original_score * 1.5


def test_disabled_boosts(retrieval_config):
    """Test disabled boost flags prevent boosting."""
    config_disabled = RetrievalConfig(
        enable_keyword_boost=False,
        enable_temporal_boost=False,
        enable_person_name_boost=False,
        enable_quoted_phrase_boost=False,
    )

    results = [create_mock_result("Alice mentioned test phrase", 0.80)]

    query_context = QueryContext(
        quoted_phrases=["test phrase"], person_names=["Alice"], reference_time=datetime.now(UTC), temporal_markers=[]
    )

    with patch("myrm_agent_harness.toolkits.memory.metrics.get_search_metrics"):
        boosted = boost_results(results, 'Alice "test phrase"', query_context, config_disabled)

        assert boosted[0].score == results[0].score


def test_result_reordering(retrieval_config):
    """Test boosting reorders results by score."""
    results = [
        create_mock_result("Low relevance", 0.60),
        create_mock_result("Contains test phrase", 0.55),
        create_mock_result("Medium relevance", 0.65),
    ]

    query_context = QueryContext(
        quoted_phrases=["test phrase"], person_names=[], reference_time=None, temporal_markers=[]
    )

    with patch("myrm_agent_harness.toolkits.memory.metrics.get_search_metrics"):
        boosted = boost_results(results, 'Find "test phrase"', query_context, retrieval_config)

        assert boosted[0].content == "Contains test phrase"
        assert boosted[0].score > boosted[1].score > boosted[2].score
