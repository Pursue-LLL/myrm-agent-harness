"""Tests for MemorySession buffering and flush operations."""

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    ProceduralMemory,
    RuleSource,
)


@pytest.fixture
def memory_config() -> MemoryConfig:
    """Create test memory configuration."""
    return MemoryConfig(embedding_model="test-model", collection_prefix="test_memory")


@pytest.fixture
def mock_vector_store():
    """Create mock vector store."""
    store = AsyncMock()
    store.upsert = AsyncMock(return_value=["mem-1"])
    store.close = AsyncMock()
    return store


@pytest.fixture
def mock_relational_store():
    """Create mock relational store."""
    store = AsyncMock()
    store.create_rule = AsyncMock()
    store.set_profile = AsyncMock()
    store.close = AsyncMock()
    return store


@pytest.fixture
def mock_embedding():
    """Create mock embedding protocol."""
    embedding = AsyncMock()
    embedding.embed = AsyncMock(return_value=[0.1] * 768)
    embedding.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    embedding.dimension = 768
    return embedding


class TestSessionMethods:
    """Test MemorySession methods to boost coverage."""

    def test_session_add_event(self, mock_vector_store, mock_embedding, memory_config):
        """Test add_event method."""
        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
        )

        session = manager.begin_session("chat-1")
        event = session.add_event("User asked a question", event_type="question", related_entities=["Python"])

        assert isinstance(event, EpisodicMemory)
        assert event.content == "User asked a question"
        assert event.event_type == "question"
        assert event.related_entities == ["Python"]
        assert session.buffer_size == 1

    def test_session_add_rule(self, mock_vector_store, mock_relational_store, mock_embedding, memory_config):
        """Test add_rule method."""
        rule_obj = ProceduralMemory(
            id="rule-1",
            content="When: trigger → Do: action",
            trigger="trigger",
            action="action",
        )
        mock_relational_store.create_rule.return_value = rule_obj

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
        )

        session = manager.begin_session("chat-1")
        rule = session.add_rule(
            trigger="user asks weather",
            action="call weather API",
            priority=1,
            source=RuleSource.USER_EXPLICIT,
            trigger_keywords=["weather", "forecast"],
        )

        assert isinstance(rule, ProceduralMemory)
        assert rule.trigger == "user asks weather"
        assert rule.action == "call weather API"
        assert rule.priority == 1
        assert rule.trigger_keywords == ["weather", "forecast"]
        assert session.buffer_size == 1

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.toolkits.memory._internal.governance_service.scan_memory_content")
    async def test_session_set_profile(
        self, mock_scan, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test set_profile method."""
        from myrm_agent_harness.toolkits.memory._internal.memory_scanner import ScanResult, ScanVerdict

        mock_scan.side_effect = lambda x, **kwargs: ScanResult(verdict=ScanVerdict.CLEAN, cleaned_text=x)
        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
        )

        session = manager.begin_session("chat-1")
        await session.set_profile("timezone", "UTC+8")

        call_args = mock_relational_store.set_profile.call_args
        assert call_args[0][:2] == ("timezone", "UTC+8")

    def test_session_search_buffer(self, mock_vector_store, mock_embedding, memory_config):
        """Test search_buffer method."""
        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
        )

        session = manager.begin_session("chat-1")
        session.add_knowledge("Python programming language")
        session.add_knowledge("JavaScript framework")
        session.add_knowledge("Python async patterns")

        results = session.search_buffer("Python", limit=2)

        assert len(results) == 2
        assert all("Python" in m.content for m in results)

    @pytest.mark.asyncio
    async def test_session_flush_empty_buffer(self, mock_vector_store, mock_embedding, memory_config):
        """Test flushing empty buffer returns empty list."""
        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
        )

        session = manager.begin_session("chat-1")
        result = await session.flush()

        assert result == []
        assert session.buffer_size == 0

    def test_session_discard(self, mock_vector_store, mock_embedding, memory_config):
        """Test discard method clears buffer and returns count."""
        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
        )

        session = manager.begin_session("chat-1")
        session.add_knowledge("Test 1")
        session.add_knowledge("Test 2")
        session.add_knowledge("Test 3")

        discarded_count = session.discard()

        assert discarded_count == 3
        assert session.buffer_size == 0

    def test_session_buffer_size_property(self, mock_vector_store, mock_embedding, memory_config):
        """Test buffer_size property."""
        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
        )

        session = manager.begin_session("chat-1")

        assert session.buffer_size == 0

        session.add_knowledge("Test 1")
        assert session.buffer_size == 1

        session.add_event("Test 2")
        assert session.buffer_size == 2
