"""Tests for MemoryManager session management and store operations."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError
from myrm_agent_harness.toolkits.memory.config import MemoryConfig, RecurrenceConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, ProceduralMemory, SemanticMemory


class TestSessionManagement:
    """Test session-related methods."""

    def test_begin_session_creates_session(self, mock_vector_store, mock_embedding, memory_config):
        """Test begin_session creates a new MemorySession."""
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        session = manager.begin_session("chat-1")

        assert session is not None
        assert manager.active_session == session

    def test_begin_session_discards_previous_session(self, mock_vector_store, mock_embedding, memory_config):
        """Test that begin_session discards the previous active session."""
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        session1 = manager.begin_session("chat-1")
        session1.add_knowledge("Test knowledge")

        session2 = manager.begin_session("chat-2")

        assert manager.active_session == session2
        assert manager.active_session != session1

    @pytest.mark.asyncio
    async def test_end_session_returns_empty_when_no_session(self, mock_vector_store, mock_embedding, memory_config):
        """Test end_session returns empty list when no active session."""
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        result = await manager.end_session()

        assert result == []

    @pytest.mark.asyncio
    async def test_end_session_flushes_and_clears(self, mock_vector_store, mock_embedding, memory_config):
        """Test end_session flushes session and clears active_session."""
        mock_vector_store.upsert.return_value = ["mem-1"]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        session = manager.begin_session("chat-1")
        session.add_knowledge("Test memory")

        result = await manager.end_session()

        assert len(result) == 1
        assert manager.active_session is None

    @pytest.mark.asyncio
    async def test_end_session_triggers_forgetting(self, mock_vector_store, mock_embedding, memory_config):
        """Test that end_session triggers forgetting at configured intervals."""
        mock_vector_store.upsert.return_value = ["mem-1"]
        forgetting_config = MemoryConfig(embedding_model="test-model", forgetting_interval=3)

        manager = MemoryManager(forgetting_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        for i in range(3):
            session = manager.begin_session(f"chat-{i}")
            session.add_knowledge(f"Memory {i}")
            await manager.end_session()

        assert manager._session_count == 3


class TestStoreOperations:
    """Test store and store_batch operations."""

    @pytest.mark.asyncio
    async def test_store_with_approval_required(self, mock_relational_store, memory_config):
        """Test store with approval_required creates pending record."""
        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True)

        memory = SemanticMemory(content="Requires approval")
        result = await manager.store(memory)

        assert result.metadata.get("_pending_id") == "pending-1"
        mock_relational_store.submit_pending.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_duplicate_pending_raises_error(self, mock_relational_store, memory_config):
        """Test storing duplicate pending memory raises error."""
        mock_relational_store.pending_exists.return_value = True
        mock_relational_store.submit_pending.return_value = ""

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True)

        memory = SemanticMemory(content="Duplicate")

        with pytest.raises(MemoryError, match="Duplicate pending memory"):
            await manager.store(memory)

    @pytest.mark.asyncio
    async def test_store_semantic_memory(self, mock_vector_store, mock_embedding, memory_config):
        """Test storing semantic memory."""
        mock_vector_store.upsert.return_value = ["mem-1"]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        memory = SemanticMemory(content="Test semantic memory")
        result = await manager.store(memory)

        assert result is not None
        assert isinstance(result, SemanticMemory)
        assert result.content == "Test semantic memory"
        mock_embedding.embed.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_episodic_memory(self, mock_vector_store, mock_embedding, memory_config):
        """Test storing episodic memory."""
        mock_vector_store.upsert.return_value = ["mem-2"]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        memory = EpisodicMemory(content="Test episodic event")
        result = await manager.store(memory)

        assert result is not None
        assert isinstance(result, EpisodicMemory)
        assert result.content == "Test episodic event"

    @pytest.mark.asyncio
    async def test_store_procedural_memory(self, mock_relational_store, memory_config):
        """Test storing procedural memory."""
        stored_rule = ProceduralMemory(
            id="rule-1",
            content="When user asks for weather, use weather API",
            trigger="weather query",
            action="call weather_api",
        )
        mock_relational_store.create_rule.return_value = stored_rule

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        memory = ProceduralMemory(
            content="When user asks for weather, use weather API", trigger="weather query", action="call weather_api"
        )
        result = await manager.store(memory)

        assert result is not None
        assert result.id == "rule-1"

    @pytest.mark.asyncio
    async def test_store_batch_empty_list(self, mock_vector_store, mock_embedding, memory_config):
        """Test store_batch with empty list returns empty."""
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        result = await manager.store_batch([])

        assert result == []

    @pytest.mark.asyncio
    async def test_store_batch_mixed_types(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test store_batch with mixed memory types."""
        mock_vector_store.upsert.side_effect = [["sem-1"], ["epi-1"]]
        rule_obj = ProceduralMemory(id="rule-1", content="Rule", trigger="trigger", action="action")
        mock_relational_store.create_rule.return_value = rule_obj

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, relational=mock_relational_store, embedding=mock_embedding
        )

        memories = [
            SemanticMemory(content="Semantic fact"),
            EpisodicMemory(content="Episodic event"),
            ProceduralMemory(content="Rule", trigger="trigger", action="action"),
        ]

        result = await manager.store_batch(memories)

        assert len(result) == 3
        assert any(isinstance(m, SemanticMemory) for m in result)
        assert any(isinstance(m, EpisodicMemory) for m in result)
        assert any(isinstance(m, ProceduralMemory) for m in result)

    @pytest.mark.asyncio
    async def test_store_batch_with_deduplicator(self, mock_vector_store, mock_embedding, memory_config):
        """Test store_batch uses deduplicator when available."""
        mock_llm = MagicMock()
        mock_vector_store.upsert.return_value = ["mem-1"]
        mock_vector_store.search.return_value = []

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, dedup_llm=mock_llm
        )

        memories = [SemanticMemory(content="Test memory")]

        result = await manager.store_batch(memories)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_store_batch_episodic_with_deduplicator(self, mock_vector_store, mock_embedding, memory_config):
        """Test store_batch deduplicates episodic memories when deduplicator available."""
        mock_llm = MagicMock()
        mock_vector_store.upsert.return_value = ["mem-1"]
        mock_vector_store.search.return_value = []

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, dedup_llm=mock_llm
        )

        memories = [EpisodicMemory(content="Test event")]

        result = await manager.store_batch(memories)

        assert len(result) == 1
        assert isinstance(result[0], EpisodicMemory)

    @pytest.mark.asyncio
    async def test_store_batch_without_deduplicator_uses_legacy_dedup(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        """Test store_batch uses legacy dedup_semantics when no deduplicator."""
        mock_vector_store.upsert.return_value = ["mem-1"]
        mock_vector_store.search.return_value = []

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        memories = [SemanticMemory(content="Test memory")]

        result = await manager.store_batch(memories)

        assert len(result) == 1


class TestCheckSessionRecurrence:
    """Test check_session_recurrence integration in MemoryManager."""

    @pytest.mark.asyncio
    async def test_recurrence_disabled_does_nothing(self, mock_vector_store, mock_embedding):
        """When recurrence is disabled, check_session_recurrence is a no-op."""
        config = MemoryConfig(
            embedding_model="test-model",
            recurrence=RecurrenceConfig(enabled=False),
        )
        manager = MemoryManager(config, user_id="u1", vector=mock_vector_store, embedding=mock_embedding)
        assert manager._recurrence_detector is None
        await manager.check_session_recurrence("user likes python")
        mock_vector_store.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_recurrence_empty_summary_skips(self, mock_vector_store, mock_embedding):
        """Empty or whitespace summary is silently skipped."""
        config = MemoryConfig(embedding_model="test-model")
        manager = MemoryManager(config, user_id="u1", vector=mock_vector_store, embedding=mock_embedding)
        await manager.check_session_recurrence("")
        await manager.check_session_recurrence("   ")
        mock_vector_store.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_recurrence_not_triggered_stores_embedding(self, mock_vector_store, mock_embedding):
        """When recurrence is not triggered, the embedding is still stored in buffer."""
        mock_vector_store.search.return_value = []
        mock_vector_store.count.return_value = 5
        config = MemoryConfig(embedding_model="test-model")
        manager = MemoryManager(config, user_id="u1", vector=mock_vector_store, embedding=mock_embedding)

        await manager.check_session_recurrence("user asked about python")

        mock_embedding.embed.assert_called_once()
        mock_vector_store.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_recurrence_triggered_stores_consolidated_memory(self, mock_vector_store, mock_embedding):
        """When recurrence is triggered, a consolidated memory is stored."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

        similar_docs = [
            MagicMock(document=VectorDocument(id=f"doc-{i}", content=f"python session {i}", vector=[0.1]*768, metadata={}), score=0.85)
            for i in range(4)
        ]
        mock_vector_store.search.return_value = similar_docs
        mock_vector_store.count.return_value = 10
        mock_vector_store.upsert.return_value = ["mem-new"]

        config = MemoryConfig(
            embedding_model="test-model",
            recurrence=RecurrenceConfig(recurrence_k=4),
        )
        manager = MemoryManager(config, user_id="u1", vector=mock_vector_store, embedding=mock_embedding)

        await manager.check_session_recurrence("user asked about python again")

        assert mock_vector_store.upsert.call_count >= 2
        assert mock_vector_store.delete.called

    @pytest.mark.asyncio
    async def test_recurrence_importance_preemption_stores_immediately(self, mock_vector_store, mock_embedding):
        """Importance preemption triggers immediate consolidation without k checks."""
        mock_vector_store.upsert.return_value = ["mem-1"]
        config = MemoryConfig(embedding_model="test-model")
        manager = MemoryManager(config, user_id="u1", vector=mock_vector_store, embedding=mock_embedding)

        await manager.check_session_recurrence("I have a severe allergy to penicillin")

        assert mock_vector_store.upsert.called

    @pytest.mark.asyncio
    async def test_recurrence_exception_is_non_fatal(self, mock_vector_store, mock_embedding):
        """Exceptions in recurrence detection are caught and logged, not propagated."""
        mock_embedding.embed.side_effect = RuntimeError("embedding service down")
        config = MemoryConfig(embedding_model="test-model")
        manager = MemoryManager(config, user_id="u1", vector=mock_vector_store, embedding=mock_embedding)

        await manager.check_session_recurrence("test topic")

    @pytest.mark.asyncio
    async def test_recurrence_with_consolidation_llm(self, mock_vector_store, mock_embedding):
        """When consolidation_llm is provided, LLM is used for consolidation."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

        similar_docs = [
            MagicMock(document=VectorDocument(id=f"doc-{i}", content=f"python data task {i}", vector=[0.1]*768, metadata={}), score=0.85)
            for i in range(4)
        ]
        mock_vector_store.search.return_value = similar_docs
        mock_vector_store.count.return_value = 10
        mock_vector_store.upsert.return_value = ["mem-new"]

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="User prefers Python for data processing"))

        config = MemoryConfig(
            embedding_model="test-model",
            recurrence=RecurrenceConfig(recurrence_k=4),
        )
        manager = MemoryManager(
            config, user_id="u1", vector=mock_vector_store,
            embedding=mock_embedding, consolidation_llm=mock_llm,
        )

        await manager.check_session_recurrence("python data processing again")

        mock_llm.ainvoke.assert_called_once()


class TestCloseSessionDrain:
    """Test that close() flushes active session before closing stores."""

    @pytest.mark.asyncio
    async def test_close_flushes_active_session(self, mock_vector_store, mock_embedding, memory_config):
        """close() must flush session buffer before closing stores."""
        mock_vector_store.upsert.return_value = ["mem-1"]
        manager = MemoryManager(memory_config, user_id="u1", vector=mock_vector_store, embedding=mock_embedding)

        session = manager.begin_session("chat-drain")
        session.add_knowledge("important preference")

        await manager.close()

        assert manager.active_session is None
        mock_vector_store.upsert.assert_called()

    @pytest.mark.asyncio
    async def test_close_noop_when_no_active_session(self, mock_vector_store, mock_embedding, memory_config):
        """close() is safe when no active session exists."""
        manager = MemoryManager(memory_config, user_id="u1", vector=mock_vector_store, embedding=mock_embedding)

        await manager.close()

        assert manager.active_session is None

    @pytest.mark.asyncio
    async def test_close_idempotent_after_end_session(self, mock_vector_store, mock_embedding, memory_config):
        """close() after end_session() does not double-flush."""
        mock_vector_store.upsert.return_value = ["mem-1"]
        manager = MemoryManager(memory_config, user_id="u1", vector=mock_vector_store, embedding=mock_embedding)

        session = manager.begin_session("chat-idem")
        session.add_knowledge("test data")

        await manager.end_session()
        mock_vector_store.upsert.reset_mock()

        await manager.close()

        mock_vector_store.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_continues_on_flush_failure(self, mock_vector_store, mock_embedding, memory_config):
        """close() still closes stores even if flush raises."""
        mock_vector_store.upsert.side_effect = OSError("disk full")
        mock_vector_store.close = AsyncMock()
        manager = MemoryManager(memory_config, user_id="u1", vector=mock_vector_store, embedding=mock_embedding)

        session = manager.begin_session("chat-fail")
        session.add_knowledge("will fail to persist")

        await manager.close()

        mock_vector_store.close.assert_called_once()
