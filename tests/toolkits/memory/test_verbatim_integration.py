"""Integration tests for verbatim conversation memory storage.

Tests the complete pipeline:
1. ConversationMemory creation
2. Chunking strategy
3. Dual-field storage (raw_exchange + content)
4. Dual-channel retrieval (raw_embedding + summary_embedding)
5. Hybrid scoring (keyword overlap + temporal boost)
6. Lazy loading (include_raw parameter)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.chunking import ChunkingStrategy, chunk_conversation
from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.query_analyzer import analyze_query
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemorySearchResult, MemoryType


class TestConversationMemoryType:
    """Test ConversationMemory type definition."""

    def test_conversation_memory_creation(self) -> None:
        memory = ConversationMemory(
            raw_exchange="User: Hello\nAssistant: Hi there!",
            content="Hello",
            timestamp=datetime.now(UTC),
        )

        assert memory.memory_type == MemoryType.CONVERSATION
        assert memory.raw_exchange
        assert memory.content
        assert memory.user_turn_only is True

    def test_without_raw_lazy_loading(self) -> None:
        memory = ConversationMemory(
            raw_exchange="User: Hello\nAssistant: Hi there!", content="Hello"
        )

        lazy_memory = memory.without_raw()

        assert lazy_memory.raw_exchange == ""
        assert lazy_memory.raw_embedding is None
        assert lazy_memory.content == "Hello"
        assert lazy_memory.display_content == "Hello"


class TestChunkingStrategy:
    """Test conversation chunking strategies."""

    def test_exchange_pair_chunking(self) -> None:
        messages = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
            {"role": "user", "content": "Is it popular?"},
            {"role": "assistant", "content": "Yes, very popular."},
        ]

        chunks = chunk_conversation(messages, ChunkingStrategy.EXCHANGE_PAIR)

        assert len(chunks) == 2
        assert "User: What is Python?" in chunks[0].raw_text
        assert "Assistant: Python is a programming language" in chunks[0].raw_text
        assert chunks[0].user_turn == "What is Python?"
        assert chunks[0].ai_turn == "Python is a programming language."

    def test_user_only_chunking(self) -> None:
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Bye"},
        ]

        chunks = chunk_conversation(messages, ChunkingStrategy.USER_ONLY)

        assert len(chunks) == 2
        assert all(c.ai_turn is None for c in chunks)

    def test_session_chunking(self) -> None:
        messages = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
        ]

        chunks = chunk_conversation(messages, ChunkingStrategy.SESSION)

        assert len(chunks) == 1
        assert "Q1" in chunks[0].raw_text
        assert "Q2" in chunks[0].raw_text
        assert "A1" in chunks[0].raw_text
        assert "A2" in chunks[0].raw_text

    def test_chunking_empty_messages(self) -> None:
        chunks = chunk_conversation([])
        assert len(chunks) == 0


class TestHybridScoring:
    """Test hybrid scoring enhancements."""

    def test_keyword_overlap_boost(self) -> None:
        config = RetrievalConfig(keyword_overlap_weight=0.15)
        retriever = MemoryRetriever(config)

        result = MemorySearchResult(
            memory=ConversationMemory(
                raw_exchange="User: I love Python programming", content="I love Python programming"
            ),
            score=0.8,
            memory_type=MemoryType.CONVERSATION,
        )

        query = "Python programming tutorial"
        ranked = retriever.rank([result], limit=10, query=query)

        assert len(ranked) == 1
        assert ranked[0].score > 0.8

    def test_temporal_proximity_boost(self) -> None:
        config = RetrievalConfig(temporal_boost_weight=0.40)
        retriever = MemoryRetriever(config)

        recent_memory = ConversationMemory(
            raw_exchange="User: Recent conversation",
            content="Recent conversation",
            timestamp=datetime.now(UTC),
        )

        result = MemorySearchResult(memory=recent_memory, score=0.7, memory_type=MemoryType.CONVERSATION)

        ranked = retriever.rank([result], limit=10, query="test")

        assert len(ranked) == 1
        assert ranked[0].score >= 0.7


class TestQueryAnalyzer:
    """Test query pattern analysis."""

    def test_quoted_phrase_extraction(self) -> None:
        query = 'I told you "do it now" yesterday'
        context = analyze_query(query)

        assert len(context.quoted_phrases) == 1
        assert "do it now" in context.quoted_phrases

    def test_person_name_extraction(self) -> None:
        query = "Ask John about the meeting with Mary"
        context = analyze_query(query)

        assert "John" in context.person_names
        assert "Mary" in context.person_names

    def test_temporal_marker_extraction(self) -> None:
        query = "What did we discuss yesterday?"
        context = analyze_query(query)

        assert len(context.temporal_markers) > 0
        assert context.reference_time is not None

    def test_quoted_phrase_various_formats(self) -> None:
        query1 = 'Use "async await" pattern'
        query2 = "Use 'async await' pattern"
        query3 = "Use 「async await」pattern"

        context1 = analyze_query(query1)
        context2 = analyze_query(query2)
        context3 = analyze_query(query3)

        assert len(context1.quoted_phrases) == 1
        assert len(context2.quoted_phrases) == 1
        assert len(context3.quoted_phrases) == 1

    def test_temporal_inference_variations(self) -> None:
        queries = [
            "last week meeting",
            "2 days ago discussion",
            "last month report",
            "today's task",
        ]

        for query in queries:
            context = analyze_query(query)
            assert len(context.temporal_markers) > 0


class TestDualChannelConfig:
    """Test dual-channel configuration."""

    def test_conversation_type_weight(self) -> None:
        config = RetrievalConfig()

        assert MemoryType.CONVERSATION in config.type_weights
        assert config.type_weights[MemoryType.CONVERSATION] == 0.95

    def test_raw_channel_enabled(self) -> None:
        config = RetrievalConfig()

        assert config.enable_conversation_raw_channel is True
        assert 0 < config.raw_channel_weight < 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
