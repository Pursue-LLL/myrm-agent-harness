"""Core tests for three-layer smart deduplication.

Focus on critical paths with minimal mocking complexity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument, VectorSearchResult
from myrm_agent_harness.toolkits.memory.strategies.deduplicator import SmartDeduplicator
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory


def make_search_result(
    content: str, similarity: float, mem_id: str = "mem1", access_count: int = 1
) -> VectorSearchResult:
    """Create VectorSearchResult with minimal fields."""
    now = datetime.now(UTC)
    return VectorSearchResult(
        document=VectorDocument(
            id=mem_id,
            content=content,
            vector=[0.5] * 768,
            created_at=now,
            updated_at=now,
            metadata={
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "access_count": access_count,
                "importance": 0.5,
                "confidence": 1.0,
                "merge_count": 0,
                "merge_history": "",
                "language": "en",
            },
        ),
        score=similarity,
    )


def make_vector_doc(
    content: str, mem_id: str = "mem1", merge_count: int = 0, importance: float = 0.5
) -> VectorDocument:
    """Create VectorDocument for vector.get() mocking."""
    now = datetime.now(UTC)
    return VectorDocument(
        id=mem_id,
        content=content,
        vector=[0.5] * 768,
        created_at=now,
        updated_at=now,
        metadata={
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "access_count": 1,
            "importance": importance,
            "confidence": 1.0,
            "merge_count": merge_count,
            "merge_history": "",
            "language": "en",
        },
    )


@pytest.fixture
def config():
    return MemoryConfig(embedding_model="test-model")


@pytest.fixture
def mock_vector():
    v = AsyncMock()
    v.search = AsyncMock(return_value=[])
    v.get = AsyncMock(return_value=[])
    return v


@pytest.fixture
def mock_embedding():
    e = AsyncMock()
    e.embed = AsyncMock(return_value=[0.1] * 768)
    e.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    return e


class TestLayer1Hash:
    """Test Hash-based exact duplicate detection."""

    @pytest.mark.asyncio
    async def test_exact_duplicate_in_batch(self, mock_vector, mock_embedding, config):
        """Test that identical content in same batch is deduplicated."""
        llm = AsyncMock()
        dedup = SmartDeduplicator(llm)

        mem1 = SemanticMemory(content="I like Python", embedding=[0.1] * 768)
        mem2 = SemanticMemory(content="I like Python", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem1, mem2], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_case_insensitive_normalization(self, mock_vector, mock_embedding, config):
        """Test that hash is case-insensitive."""
        llm = AsyncMock()
        dedup = SmartDeduplicator(llm)

        mem1 = SemanticMemory(content="  PYTHON  ", embedding=[0.1] * 768)
        mem2 = SemanticMemory(content="python", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem1, mem2], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1


class TestLayer2Vector:
    """Test Vector similarity-based filtering."""

    @pytest.mark.asyncio
    async def test_high_similarity_skipped(self, mock_vector, mock_embedding, config):
        """Test similarity ≥0.95 is treated as DUPLICATE."""
        llm = AsyncMock()
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("timeout 5 seconds", 0.96)]

        mem = SemanticMemory(content="timeout 5s", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 0
        assert not llm.ainvoke.called

    @pytest.mark.asyncio
    async def test_low_similarity_created(self, mock_vector, mock_embedding, config):
        """Test similarity <0.60 creates NEW without LLM."""
        llm = AsyncMock()
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = []

        mem = SemanticMemory(content="New topic", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert not llm.ainvoke.called


class TestLayer3LLM:
    """Test LLM semantic judgment."""

    @pytest.mark.asyncio
    async def test_update_replace(self, mock_vector, mock_embedding, config):
        """Test UPDATE_REPLACE for parameter changes."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content="DECISION: UPDATE_REPLACE\nREASON: Upgrade\nMERGED: Pool 50 (was 10)")
        )
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Pool size 10", 0.88)]
        mock_vector.get.return_value = [make_vector_doc("Pool size 10")]

        mem = SemanticMemory(content="Pool size 50", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert "50" in result[0].content
        assert result[0].merge_count == 1
        assert "REPLACE" in result[0].merge_history
        assert llm.ainvoke.called

    @pytest.mark.asyncio
    async def test_update_merge(self, mock_vector, mock_embedding, config):
        """Test UPDATE_MERGE for incremental features."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content="DECISION: UPDATE_MERGE\nREASON: Additive\nMERGED: Redis + backup")
        )
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Use Redis", 0.72)]
        mock_vector.get.return_value = [make_vector_doc("Use Redis")]

        mem = SemanticMemory(content="Added backup", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert "backup" in result[0].content
        assert result[0].merge_count == 1
        assert "MERGE" in result[0].merge_history

    @pytest.mark.asyncio
    async def test_duplicate_skipped(self, mock_vector, mock_embedding, config):
        """Test DUPLICATE decision skips memory."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: DUPLICATE\nREASON: Same meaning"))
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("timeout 5 seconds", 0.86)]

        mem = SemanticMemory(content="timeout 5s", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_new_independent_memory(self, mock_vector, mock_embedding, config):
        """Test NEW decision for independent memories."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: NEW\nREASON: Different events"))
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Deployed March 10", 0.91)]

        mem = EpisodicMemory(content="Deployed March 16", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert result[0].content == "Deployed March 16"


class TestMergeTracking:
    """Test merge_count and merge_history tracking."""

    @pytest.mark.asyncio
    async def test_merge_count_incremented(self, mock_vector, mock_embedding, config):
        """Test merge_count increases on UPDATE."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: UPDATE_REPLACE\nMERGED: New"))
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Old", 0.80)]

        doc = make_vector_doc("Old", merge_count=2)
        doc.metadata["merge_history"] = "03-10 10:00|REPLACE|prev"
        mock_vector.get.return_value = [doc]

        mem = SemanticMemory(content="Upgraded", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert result[0].merge_count == 3

    @pytest.mark.asyncio
    async def test_importance_boost(self, mock_vector, mock_embedding, config):
        """Test importance is boosted on UPDATE."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: UPDATE_REPLACE\nMERGED: Updated"))
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Old", 0.80)]
        mock_vector.get.return_value = [make_vector_doc("Old")]

        mem = SemanticMemory(content="New", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert result[0].importance == 0.55

    @pytest.mark.asyncio
    async def test_importance_capped(self, mock_vector, mock_embedding, config):
        """Test importance never exceeds 1.0."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: UPDATE_REPLACE\nMERGED: Updated"))
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Old", 0.80)]

        doc = make_vector_doc("Old")
        doc.metadata["importance"] = 0.98
        mock_vector.get.return_value = [doc]

        mem = SemanticMemory(content="New", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert result[0].importance == 1.0

    @pytest.mark.asyncio
    async def test_embedding_cleared_after_update(self, mock_vector, mock_embedding, config):
        """Test embedding is cleared after content update."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: UPDATE_REPLACE\nMERGED: Updated content"))
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Old content", 0.80)]
        mock_vector.get.return_value = [make_vector_doc("Old content")]

        mem = SemanticMemory(content="New content", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert result[0].embedding is None


class TestEdgeCases:
    """Test error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_empty_batch(self, mock_vector, mock_embedding, config):
        """Test empty batch returns empty result."""
        llm = AsyncMock()
        dedup = SmartDeduplicator(llm)

        result = await dedup.deduplicate_batch(
            [], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_llm_failure_defaults_to_new(self, mock_vector, mock_embedding, config):
        """Test LLM failure gracefully falls back to NEW."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Similar", 0.75)]

        mem = SemanticMemory(content="Related", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_target_not_found_fallback(self, mock_vector, mock_embedding, config):
        """Test missing target memory creates NEW."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: UPDATE_REPLACE\nMERGED: Updated"))
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Old", 0.85)]
        mock_vector.get.return_value = []

        mem = SemanticMemory(content="New", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert result[0].content == "New"

    @pytest.mark.asyncio
    async def test_missing_embedding_generated(self, mock_vector, mock_embedding, config):
        """Test missing embeddings are auto-generated."""
        llm = AsyncMock()
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = []

        mem = SemanticMemory(content="Test", embedding=None)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert mock_embedding.embed_batch.called
        assert result[0].embedding is not None


class TestStatistics:
    """Test logging and statistics."""

    @pytest.mark.asyncio
    async def test_statistics_logged(self, mock_vector, mock_embedding, config):
        """Test dedup statistics are logged."""
        llm = AsyncMock()
        dedup = SmartDeduplicator(llm)

        mem1 = SemanticMemory(content="A", embedding=[0.1] * 768)
        mem2 = SemanticMemory(content="A", embedding=[0.1] * 768)
        mem3 = SemanticMemory(content="B", embedding=[0.2] * 768)

        mock_vector.search.return_value = []

        with patch("myrm_agent_harness.toolkits.memory.strategies.deduplicator.logger") as mock_logger:
            result = await dedup.deduplicate_batch(
                [mem1, mem2, mem3], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
            )

            assert len(result) == 2
            assert mock_logger.warning.called


class TestBoundaryConditions:
    """Test threshold boundary conditions."""

    @pytest.mark.asyncio
    async def test_exact_threshold_095(self, mock_vector, mock_embedding, config):
        """Test similarity exactly at 0.95."""
        llm = AsyncMock()
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Test", 0.95)]

        mem = SemanticMemory(content="Test variant", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 0
        assert not llm.ainvoke.called

    @pytest.mark.asyncio
    async def test_just_below_threshold_094(self, mock_vector, mock_embedding, config):
        """Test similarity 0.949 triggers LLM."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: NEW\nREASON: Different"))
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Test", 0.949)]

        mem = SemanticMemory(content="Test variant", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert llm.ainvoke.called


class TestConcurrentProcessing:
    """Test batch concurrent processing."""

    @pytest.mark.asyncio
    async def test_multiple_memories_concurrent(self, mock_vector, mock_embedding, config):
        """Test multiple memories processed concurrently."""
        llm = AsyncMock()
        dedup = SmartDeduplicator(llm)

        memories = [SemanticMemory(content=f"Memory {i}", embedding=[float(i)] * 768) for i in range(5)]

        mock_vector.search.return_value = []

        result = await dedup.deduplicate_batch(
            memories, vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 5
        assert mock_vector.search.call_count == 5


class TestRaceConditionProtection:
    """Test protection against concurrent UPDATE race conditions."""

    @pytest.mark.asyncio
    async def test_concurrent_updates_to_same_target(self, mock_vector, mock_embedding, config):
        """Test that concurrent UPDATEs to same target are prevented."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content="DECISION: UPDATE_REPLACE\nREASON: Update\nMERGED: Updated value")
        )
        dedup = SmartDeduplicator(llm)

        mock_vector.search.return_value = [make_search_result("Old value", 0.80, mem_id="target_123")]
        mock_vector.get.return_value = [make_vector_doc("Old value", mem_id="target_123")]

        mem1 = SemanticMemory(content="Value 50", embedding=[0.1] * 768)
        mem2 = SemanticMemory(content="Value 100", embedding=[0.2] * 768)

        result = await dedup.deduplicate_batch(
            [mem1, mem2], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 2


class TestTimeWindowLogic:
    """Test time window awareness in LLM judgment."""

    @pytest.mark.asyncio
    async def test_recent_memory_marked_in_prompt(self, mock_vector, mock_embedding, config):
        """Test that recent memories (<24h) are marked in LLM prompt."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: NEW\nREASON: Recent but distinct"))
        dedup = SmartDeduplicator(llm, time_window_hours=24)

        from datetime import timedelta

        recent_time = datetime.now(UTC) - timedelta(hours=12)
        doc = make_vector_doc("Recent memory", mem_id="mem1")
        doc.created_at = recent_time
        doc.metadata["created_at"] = recent_time.isoformat()

        mock_vector.search.return_value = [VectorSearchResult(document=doc, score=0.75)]

        mem = SemanticMemory(content="Related memory", embedding=[0.1] * 768)

        await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert llm.ainvoke.called
        call_args = llm.ainvoke.call_args[0][0]
        prompt = str(call_args[1].content)
        assert "RECENT" in prompt or "24h" in prompt


class TestMetadataMerge:
    """Test metadata handling during UPDATE operations."""

    @pytest.mark.asyncio
    async def test_update_replace_replaces_metadata(self, mock_vector, mock_embedding, config):
        """UPDATE_REPLACE should fully replace existing metadata with new."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: UPDATE_REPLACE\nMERGED: New config"))
        dedup = SmartDeduplicator(llm)

        existing_doc = make_vector_doc("Old config")
        existing_doc.metadata["custom_field"] = "old_value"
        existing_doc.metadata["source_chat_id"] = "chat-old"
        existing_doc.metadata["source_message_id"] = "msg-old"
        existing_doc.metadata["tags"] = "tag1"

        mock_vector.search.return_value = [make_search_result("Old config", 0.88)]
        mock_vector.get.return_value = [existing_doc]

        mem = SemanticMemory(
            content="New config",
            embedding=[0.1] * 768,
            metadata={"custom_field": "new_value", "extra": "data"},
            source_chat_id="chat-new",
            source_message_id="msg-new",
        )

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert result[0].metadata["custom_field"] == "new_value"
        assert result[0].metadata["extra"] == "data"
        assert result[0].source_chat_id == "chat-new"
        assert result[0].source_message_id == "msg-new"

    @pytest.mark.asyncio
    async def test_update_merge_merges_metadata(self, mock_vector, mock_embedding, config):
        """UPDATE_MERGE should merge new metadata into existing."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: UPDATE_MERGE\nMERGED: Redis + backup"))
        dedup = SmartDeduplicator(llm)

        existing_doc = make_vector_doc("Use Redis")
        existing_doc.metadata["env"] = "production"
        existing_doc.metadata["tags"] = "redis"

        mock_vector.search.return_value = [make_search_result("Use Redis", 0.72)]
        mock_vector.get.return_value = [existing_doc]

        mem = SemanticMemory(
            content="Added backup",
            embedding=[0.1] * 768,
            metadata={"version": "2.0"},
            tags=["backup", "redis"],
            source_chat_id="chat-latest",
        )

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert result[0].metadata.get("env") == "production"
        assert result[0].metadata.get("version") == "2.0"
        assert result[0].source_chat_id == "chat-latest"

    @pytest.mark.asyncio
    async def test_update_merge_tags_deduplicated(self, mock_vector, mock_embedding, config):
        """UPDATE_MERGE should union-merge tags and deduplicate."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: UPDATE_MERGE\nMERGED: Combined content"))
        dedup = SmartDeduplicator(llm)

        existing_doc = make_vector_doc("Original")
        existing_doc.metadata["tags"] = "python,redis"

        mock_vector.search.return_value = [make_search_result("Original", 0.72)]
        mock_vector.get.return_value = [existing_doc]

        mem = SemanticMemory(content="Extended", embedding=[0.1] * 768, tags=["redis", "docker"])

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        tags = result[0].tags
        assert "redis" in tags
        assert "docker" in tags
        assert len(tags) == len(set(tags))

    @pytest.mark.asyncio
    async def test_update_empty_metadata_preserves_existing(self, mock_vector, mock_embedding, config):
        """When new memory has empty metadata, existing metadata is preserved."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: UPDATE_MERGE\nMERGED: Same content"))
        dedup = SmartDeduplicator(llm)

        existing_doc = make_vector_doc("Content")
        existing_doc.metadata["env"] = "staging"

        mock_vector.search.return_value = [make_search_result("Content", 0.72)]
        mock_vector.get.return_value = [existing_doc]

        mem = SemanticMemory(content="Updated content", embedding=[0.1] * 768)

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert result[0].metadata.get("env") == "staging"

    @pytest.mark.asyncio
    async def test_source_fields_always_update_to_latest(self, mock_vector, mock_embedding, config):
        """source_chat_id and source_message_id should always track the latest provenance."""
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="DECISION: UPDATE_REPLACE\nMERGED: Updated"))
        dedup = SmartDeduplicator(llm)

        existing_doc = make_vector_doc("Old")
        existing_doc.metadata["source_chat_id"] = "chat-1"
        existing_doc.metadata["source_message_id"] = "msg-1"

        mock_vector.search.return_value = [make_search_result("Old", 0.88)]
        mock_vector.get.return_value = [existing_doc]

        mem = SemanticMemory(content="New", embedding=[0.1] * 768, source_chat_id="chat-2", source_message_id="msg-2")

        result = await dedup.deduplicate_batch(
            [mem], vector=mock_vector, embedding=mock_embedding, memory_config=config, cache=None
        )

        assert len(result) == 1
        assert result[0].source_chat_id == "chat-2"
        assert result[0].source_message_id == "msg-2"
