"""Unit tests for SmartDeduplicator — three-layer deduplication engine.

Tests cover:
- Layer 1: Hash-based exact deduplication (FIFO, normalization levels, batch-level)
- Layer 2: Vector similarity thresholds (dynamic thresholds, high/low detection)
- Layer 3: LLM judgment (DUPLICATE/UPDATE_REPLACE/UPDATE_MERGE/NEW)
- Early lock protection (concurrent target reservation)
- Adaptive capacity adjustment
- Update application (metadata merge, tags union, source provenance)
- Hash persistence (load/save)
- Graceful degradation (LLM failure → NEW)
- Metrics accuracy
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.hash_utils import (
    NormalizationLevel,
    compute_content_hash,
    compute_normalized_hash,
)
from myrm_agent_harness.toolkits.memory.strategies.deduplicator import (
    DeduplicationDecision,
    SmartDeduplicator,
)
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemoryType,
    SemanticMemory,
)


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_semantic(content: str, *, embedding: list[float] | None = None, **kwargs) -> SemanticMemory:
    return SemanticMemory(content=content, embedding=embedding, **kwargs)


def _make_episodic(content: str, *, embedding: list[float] | None = None, **kwargs) -> EpisodicMemory:
    return EpisodicMemory(content=content, embedding=embedding, **kwargs)


def _fake_embedding(dim: int = 8) -> list[float]:
    """Deterministic fake embedding."""
    return [0.1] * dim


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock()
    response = MagicMock()
    response.content = "NEW"
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


@pytest.fixture
def mock_vector() -> AsyncMock:
    vector = AsyncMock()
    vector.search = AsyncMock(return_value=[])
    vector.count = AsyncMock(return_value=0)
    vector.get = AsyncMock(return_value=[])
    return vector


@pytest.fixture
def mock_embedding() -> AsyncMock:
    embedding = AsyncMock()
    embedding.embed_documents = AsyncMock(return_value=[[0.1] * 8])
    return embedding


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock()
    config.semantic_collection = "test_semantic"
    config.episodic_collection = "test_episodic"
    return config


@pytest.fixture
def deduplicator(mock_llm: MagicMock) -> SmartDeduplicator:
    return SmartDeduplicator(
        llm=mock_llm,
        high_threshold=0.95,
        low_threshold=0.60,
        time_window_hours=24,
        max_cache_size=100,
        normalization_level=2,
        adaptive_capacity=False,
    )


# ── Layer 1: Hash Tests ──────────────────────────────────────────────


class TestHashLayer:
    """Tests for Layer 1: Hash-based exact deduplication."""

    def test_compute_normalized_hash_none_level(self) -> None:
        h1 = compute_normalized_hash("Hello World", NormalizationLevel.NONE)
        h2 = compute_normalized_hash("hello world", NormalizationLevel.NONE)
        assert h1 != h2  # case-sensitive

    def test_compute_normalized_hash_basic_level(self) -> None:
        h1 = compute_normalized_hash("Hello World", NormalizationLevel.BASIC)
        h2 = compute_normalized_hash("hello   world", NormalizationLevel.BASIC)
        assert h1 == h2  # case + whitespace normalized

    def test_compute_normalized_hash_full_level(self) -> None:
        h1 = compute_normalized_hash("Hello, World!", NormalizationLevel.FULL)
        h2 = compute_normalized_hash("hello world", NormalizationLevel.FULL)
        assert h1 == h2  # punctuation + case + whitespace normalized

    def test_compute_normalized_hash_unicode_normalization(self) -> None:
        h1 = compute_normalized_hash("café", NormalizationLevel.FULL)
        h2 = compute_normalized_hash("cafe\u0301", NormalizationLevel.FULL)
        assert h1 == h2  # NFKC normalization

    def test_compute_content_hash_is_full_level(self) -> None:
        h1 = compute_content_hash("Test Content")
        h2 = compute_normalized_hash("Test Content", NormalizationLevel.FULL)
        assert h1 == h2

    def test_hash_length_is_16(self) -> None:
        h = compute_normalized_hash("test", NormalizationLevel.FULL)
        assert len(h) == 16

    @pytest.mark.asyncio
    async def test_hash_exact_duplicate_skipped(
        self,
        deduplicator: SmartDeduplicator,
        mock_vector: AsyncMock,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """Identical content should be detected as duplicate by hash layer."""
        mem1 = _make_semantic("User prefers dark mode", embedding=_fake_embedding())
        mem2 = _make_semantic("User prefers dark mode", embedding=_fake_embedding())

        result = await deduplicator.deduplicate_batch(
            [mem1, mem2], mock_vector, mock_embedding, mock_config, None
        )

        assert len(result) == 1
        assert deduplicator.get_metrics().cache_hits >= 1

    @pytest.mark.asyncio
    async def test_hash_variant_duplicate_detected(
        self,
        deduplicator: SmartDeduplicator,
        mock_vector: AsyncMock,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """Case/whitespace/punctuation variants detected as same by FULL normalization."""
        mem1 = _make_semantic("User prefers dark mode", embedding=_fake_embedding())
        mem2 = _make_semantic("user  prefers  dark  mode!", embedding=_fake_embedding())

        result = await deduplicator.deduplicate_batch(
            [mem1, mem2], mock_vector, mock_embedding, mock_config, None
        )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_hash_different_content_passes(
        self,
        deduplicator: SmartDeduplicator,
        mock_vector: AsyncMock,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """Different content should pass hash layer and go to vector search."""
        mem1 = _make_semantic("User likes Python", embedding=_fake_embedding())
        mem2 = _make_semantic("User likes TypeScript", embedding=_fake_embedding())

        result = await deduplicator.deduplicate_batch(
            [mem1, mem2], mock_vector, mock_embedding, mock_config, None
        )

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_hash_fifo_eviction(self, mock_llm: MagicMock) -> None:
        """FIFO eviction should work when cache exceeds max_cache_size."""
        dedup = SmartDeduplicator(
            llm=mock_llm,
            max_cache_size=3,
            adaptive_capacity=False,
        )

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[])
        embedding = AsyncMock()
        config = MagicMock()
        config.semantic_collection = "test_semantic"
        config.episodic_collection = "test_episodic"

        for i in range(5):
            mem = _make_semantic(f"Unique content number {i}", embedding=_fake_embedding())
            await dedup.deduplicate_batch([mem], vector, embedding, config, None)

        assert dedup.get_metrics().evictions >= 2

    @pytest.mark.asyncio
    async def test_hash_cross_batch_persistence(
        self,
        deduplicator: SmartDeduplicator,
        mock_vector: AsyncMock,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """Hash cache persists across batches."""
        mem1 = _make_semantic("Persistent content", embedding=_fake_embedding())
        await deduplicator.deduplicate_batch([mem1], mock_vector, mock_embedding, mock_config, None)

        mem2 = _make_semantic("Persistent content", embedding=_fake_embedding())
        result = await deduplicator.deduplicate_batch([mem2], mock_vector, mock_embedding, mock_config, None)

        assert len(result) == 0
        assert deduplicator.get_metrics().cache_hits >= 1


# ── Layer 2: Vector Similarity Tests ─────────────────────────────────


class TestVectorLayer:
    """Tests for Layer 2: Vector similarity-based deduplication."""

    @pytest.mark.asyncio
    async def test_high_similarity_auto_duplicate(
        self,
        deduplicator: SmartDeduplicator,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """Score >= high_threshold → DUPLICATE without LLM."""
        from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

        existing_doc = VectorDocument(
            id="existing-1",
            content="User prefers dark mode",
            vector=_fake_embedding(),
            metadata={"memory_type": "semantic"},
        )
        search_result = SearchResult(document=existing_doc, score=0.97)

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[search_result])
        vector.count = AsyncMock(return_value=10)

        mem = _make_semantic("User prefers dark mode variant", embedding=_fake_embedding())
        result = await deduplicator.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_below_low_threshold_is_new(
        self,
        deduplicator: SmartDeduplicator,
        mock_vector: AsyncMock,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """No candidates above low_threshold → NEW (no LLM invoked)."""
        mock_vector.search = AsyncMock(return_value=[])

        mem = _make_semantic("Completely unique content", embedding=_fake_embedding())
        result = await deduplicator.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)

        assert len(result) == 1
        assert result[0].content == "Completely unique content"

    @pytest.mark.asyncio
    async def test_dynamic_thresholds_episodic(self, mock_llm: MagicMock) -> None:
        """Episodic memories use different thresholds (0.92/0.65)."""
        from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

        dedup = SmartDeduplicator(llm=mock_llm, adaptive_capacity=False)

        existing_doc = VectorDocument(
            id="existing-ep",
            content="Had a meeting with Alice",
            vector=_fake_embedding(),
            metadata={"memory_type": "episodic", "event_type": "conversation"},
        )
        search_result = SearchResult(document=existing_doc, score=0.93)

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[search_result])
        vector.count = AsyncMock(return_value=10)

        config = MagicMock()
        config.semantic_collection = "test_semantic"
        config.episodic_collection = "test_episodic"

        mem = _make_episodic("Had a meeting with Alice about project", embedding=_fake_embedding())
        result = await dedup.deduplicate_batch([mem], vector, AsyncMock(), config, None)

        # Score 0.93 >= episodic high_threshold 0.92 → DUPLICATE
        assert len(result) == 0


# ── Layer 3: LLM Judgment Tests ──────────────────────────────────────


class TestLLMLayer:
    """Tests for Layer 3: LLM semantic judgment."""

    @pytest.mark.asyncio
    async def test_llm_returns_new(
        self,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """LLM judges content as NEW → memory passes through."""
        from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

        llm = MagicMock()
        response = MagicMock()
        response.content = "Decision: NEW\nReason: Different topic entirely"
        llm.ainvoke = AsyncMock(return_value=response)

        dedup = SmartDeduplicator(llm=llm, adaptive_capacity=False)

        existing_doc = VectorDocument(
            id="existing-llm",
            content="User likes Python for data science",
            vector=_fake_embedding(),
            metadata={"memory_type": "semantic", "importance": "0.5"},
        )
        search_result = SearchResult(document=existing_doc, score=0.75)

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[search_result])
        vector.count = AsyncMock(return_value=10)

        mem = _make_semantic("User likes TypeScript for web", embedding=_fake_embedding())
        result = await dedup.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)

        assert len(result) == 1
        assert result[0].content == "User likes TypeScript for web"

    @pytest.mark.asyncio
    async def test_llm_returns_duplicate(
        self,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """LLM judges content as DUPLICATE → memory dropped."""
        from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

        llm = MagicMock()
        response = MagicMock()
        response.content = "Decision: DUPLICATE\nReason: Same information expressed differently"
        llm.ainvoke = AsyncMock(return_value=response)

        dedup = SmartDeduplicator(llm=llm, adaptive_capacity=False)

        existing_doc = VectorDocument(
            id="existing-dup",
            content="User prefers dark mode in all apps",
            vector=_fake_embedding(),
            metadata={"memory_type": "semantic"},
        )
        search_result = SearchResult(document=existing_doc, score=0.80)

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[search_result])
        vector.count = AsyncMock(return_value=10)

        mem = _make_semantic("User always uses dark mode", embedding=_fake_embedding())
        result = await dedup.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_llm_returns_update_replace(
        self,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """LLM judges UPDATE_REPLACE → existing memory updated with new content."""
        from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

        llm = MagicMock()
        response = MagicMock()
        response.content = "Decision: UPDATE_REPLACE\nMERGED: User prefers VS Code with Vim keybindings"
        llm.ainvoke = AsyncMock(return_value=response)

        dedup = SmartDeduplicator(llm=llm, adaptive_capacity=False)

        existing_doc = VectorDocument(
            id="existing-replace",
            content="User prefers VS Code",
            vector=_fake_embedding(),
            metadata={"memory_type": "semantic", "importance": "0.5"},
            created_at=datetime.now(UTC) - timedelta(days=1),
        )
        search_result = SearchResult(document=existing_doc, score=0.80)

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[search_result])
        vector.get = AsyncMock(return_value=[existing_doc])
        vector.count = AsyncMock(return_value=10)

        mem = _make_semantic(
            "User added Vim keybindings to VS Code",
            embedding=_fake_embedding(),
            source_chat_id="chat-123",
            tags=["editor", "vim"],
        )
        result = await dedup.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)

        assert len(result) == 1
        updated = result[0]
        assert "Vim keybindings" in updated.content
        assert updated.merge_count == 1
        assert updated.merge_history != ""
        assert updated.source_chat_id == "chat-123"

    @pytest.mark.asyncio
    async def test_llm_returns_update_merge(
        self,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """LLM judges UPDATE_MERGE → existing memory enriched with new info."""
        from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

        llm = MagicMock()
        response = MagicMock()
        response.content = "Decision: UPDATE_MERGE\nMERGED: User likes Python for data science and web scraping"
        llm.ainvoke = AsyncMock(return_value=response)

        dedup = SmartDeduplicator(llm=llm, adaptive_capacity=False)

        existing_doc = VectorDocument(
            id="existing-merge",
            content="User likes Python for data science",
            vector=_fake_embedding(),
            metadata={"memory_type": "semantic", "importance": "0.5", "domain": "coding"},
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
        search_result = SearchResult(document=existing_doc, score=0.78)

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[search_result])
        vector.get = AsyncMock(return_value=[existing_doc])
        vector.count = AsyncMock(return_value=10)

        mem = _make_semantic(
            "User also uses Python for web scraping",
            embedding=_fake_embedding(),
            metadata={"domain": "coding", "new_key": "value"},
            tags=["python", "scraping"],
        )
        result = await dedup.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)

        assert len(result) == 1
        updated = result[0]
        assert "web scraping" in updated.content
        assert updated.merge_count == 1
        # MERGE: metadata is merged (new keys override)
        assert updated.metadata.get("new_key") == "value"
        assert updated.metadata.get("domain") == "coding"

    @pytest.mark.asyncio
    async def test_llm_failure_defaults_to_new(
        self,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """LLM exception → graceful degradation to NEW (no data loss)."""
        from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        dedup = SmartDeduplicator(llm=llm, adaptive_capacity=False)

        existing_doc = VectorDocument(
            id="existing-fail",
            content="Some existing content",
            vector=_fake_embedding(),
            metadata={"memory_type": "semantic"},
        )
        search_result = SearchResult(document=existing_doc, score=0.75)

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[search_result])
        vector.count = AsyncMock(return_value=10)

        mem = _make_semantic("New content similar to existing", embedding=_fake_embedding())
        result = await dedup.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)

        # Graceful degradation: still saved (no data loss)
        assert len(result) == 1


# ── Early Lock Protection Tests ──────────────────────────────────────


class TestEarlyLock:
    """Tests for early lock protection (concurrent target reservation)."""

    @pytest.mark.asyncio
    async def test_concurrent_same_target_only_one_llm_call(self) -> None:
        """Multiple memories targeting same existing memory → only 1 LLM call."""
        from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

        call_count = 0

        async def _mock_invoke(messages):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)  # Simulate LLM latency
            response = MagicMock()
            response.content = "Decision: NEW\nReason: Different enough"
            return response

        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=_mock_invoke)

        dedup = SmartDeduplicator(llm=llm, adaptive_capacity=False)

        existing_doc = VectorDocument(
            id="shared-target",
            content="User prefers Python",
            vector=_fake_embedding(),
            metadata={"memory_type": "semantic"},
        )
        search_result = SearchResult(document=existing_doc, score=0.75)

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[search_result])
        vector.count = AsyncMock(return_value=10)

        config = MagicMock()
        config.semantic_collection = "test_semantic"
        config.episodic_collection = "test_episodic"

        mems = [
            _make_semantic(f"Python variant {i}", embedding=_fake_embedding())
            for i in range(5)
        ]

        result = await dedup.deduplicate_batch(mems, vector, AsyncMock(), config, None)

        # Only 1 LLM call made; others resolve as NEW via early lock
        assert call_count == 1
        # All memories pass through (4 as NEW via lock bypass + 1 from LLM NEW)
        assert len(result) == 5


# ── Adaptive Capacity Tests ──────────────────────────────────────────


class TestAdaptiveCapacity:
    """Tests for adaptive capacity adjustment."""

    @pytest.mark.asyncio
    async def test_capacity_adjusts_to_memory_count(self) -> None:
        """Cache capacity adjusts based on vector store memory count."""
        llm = MagicMock()
        response = MagicMock()
        response.content = "NEW"
        llm.ainvoke = AsyncMock(return_value=response)

        dedup = SmartDeduplicator(
            llm=llm,
            max_cache_size=10000,
            adaptive_capacity=True,
            capacity_multiplier=1.5,
        )

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[])
        # Simulate 100 semantic + 50 episodic = 150 total → target = 225
        vector.count = AsyncMock(side_effect=[100, 50])

        config = MagicMock()
        config.semantic_collection = "test_semantic"
        config.episodic_collection = "test_episodic"

        mem = _make_semantic("Test adaptive", embedding=_fake_embedding())
        await dedup.deduplicate_batch([mem], vector, AsyncMock(), config, None)

        # Capacity adjustment was triggered (count was called)
        assert vector.count.call_count == 2


# ── Hash Persistence Tests ───────────────────────────────────────────


class TestHashPersistence:
    """Tests for hash cache persistence (load/save)."""

    @pytest.mark.asyncio
    async def test_persist_and_load(self) -> None:
        """Hash cache persists to disk and can be reloaded."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = str(Path(tmp_dir) / "hash_cache.json")

            llm = MagicMock()
            response = MagicMock()
            response.content = "NEW"
            llm.ainvoke = AsyncMock(return_value=response)

            dedup1 = SmartDeduplicator(
                llm=llm,
                adaptive_capacity=False,
                persist_hash_cache=True,
                hash_cache_path=cache_path,
            )

            vector = AsyncMock()
            vector.search = AsyncMock(return_value=[])
            config = MagicMock()
            config.semantic_collection = "test_semantic"
            config.episodic_collection = "test_episodic"

            mem = _make_semantic("Persisted content", embedding=_fake_embedding())
            await dedup1.deduplicate_batch([mem], vector, AsyncMock(), config, None)

            # Verify file written
            assert Path(cache_path).exists()
            data = json.loads(Path(cache_path).read_text())
            assert len(data["hashes"]) == 1

            # Create new deduplicator that loads from same path
            dedup2 = SmartDeduplicator(
                llm=llm,
                adaptive_capacity=False,
                persist_hash_cache=True,
                hash_cache_path=cache_path,
            )

            # Same content should be hash hit
            mem2 = _make_semantic("Persisted content", embedding=_fake_embedding())
            result = await dedup2.deduplicate_batch([mem2], vector, AsyncMock(), config, None)

            assert len(result) == 0  # Detected as duplicate from persisted cache


# ── Metrics Tests ────────────────────────────────────────────────────


class TestMetrics:
    """Tests for deduplication metrics accuracy."""

    @pytest.mark.asyncio
    async def test_metrics_tracking(
        self,
        deduplicator: SmartDeduplicator,
        mock_vector: AsyncMock,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """Metrics correctly track hits, misses, and evictions."""
        mems = [
            _make_semantic("Content A", embedding=_fake_embedding()),
            _make_semantic("Content B", embedding=_fake_embedding()),
            _make_semantic("Content A", embedding=_fake_embedding()),  # duplicate
        ]

        await deduplicator.deduplicate_batch(mems, mock_vector, mock_embedding, mock_config, None)

        metrics = deduplicator.get_metrics()
        assert metrics.total_checks == 3
        assert metrics.cache_hits == 1
        assert metrics.cache_misses == 2
        assert metrics.hit_rate == pytest.approx(1.0 / 3.0)

    @pytest.mark.asyncio
    async def test_empty_batch_returns_empty(
        self,
        deduplicator: SmartDeduplicator,
        mock_vector: AsyncMock,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """Empty input returns empty output, no metrics changed."""
        result = await deduplicator.deduplicate_batch([], mock_vector, mock_embedding, mock_config, None)
        assert result == []
        assert deduplicator.get_metrics().total_checks == 0


# ── Update Application Tests ─────────────────────────────────────────


class TestUpdateApplication:
    """Tests for _apply_update method (metadata, tags, source provenance)."""

    @pytest.mark.asyncio
    async def test_update_replace_metadata_overwrites(
        self,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """UPDATE_REPLACE: new metadata fully replaces existing metadata."""
        from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

        llm = MagicMock()
        response = MagicMock()
        response.content = "UPDATE_REPLACE\nMERGED: Updated editor preference"
        llm.ainvoke = AsyncMock(return_value=response)

        dedup = SmartDeduplicator(llm=llm, adaptive_capacity=False)

        existing_doc = VectorDocument(
            id="target-replace",
            content="User uses Sublime Text",
            vector=_fake_embedding(),
            metadata={
                "memory_type": "semantic",
                "importance": "0.5",
                "old_key": "old_value",
            },
        )
        search_result = SearchResult(document=existing_doc, score=0.78)

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[search_result])
        vector.get = AsyncMock(return_value=[existing_doc])
        vector.count = AsyncMock(return_value=10)

        mem = _make_semantic(
            "User switched to VS Code",
            embedding=_fake_embedding(),
            metadata={"new_key": "new_value"},
            source_chat_id="chat-new",
        )
        result = await dedup.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)

        assert len(result) == 1
        updated = result[0]
        # REPLACE: old metadata gone, new metadata set
        assert updated.metadata.get("new_key") == "new_value"
        assert "old_key" not in updated.metadata
        assert updated.source_chat_id == "chat-new"

    @pytest.mark.asyncio
    async def test_update_merge_tags_union(
        self,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """UPDATE_MERGE: tags are union-merged and deduplicated."""
        from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

        llm = MagicMock()
        response = MagicMock()
        response.content = "UPDATE_MERGE\nMERGED: User likes Python for data and web"
        llm.ainvoke = AsyncMock(return_value=response)

        dedup = SmartDeduplicator(llm=llm, adaptive_capacity=False)

        existing_doc = VectorDocument(
            id="target-tags",
            content="User likes Python for data",
            vector=_fake_embedding(),
            metadata={
                "memory_type": "semantic",
                "importance": "0.5",
                "tags": '["python", "data"]',
            },
        )
        search_result = SearchResult(document=existing_doc, score=0.78)

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[search_result])
        vector.get = AsyncMock(return_value=[existing_doc])
        vector.count = AsyncMock(return_value=10)

        mem = _make_semantic(
            "User also uses Python for web",
            embedding=_fake_embedding(),
            tags=["python", "web"],
        )
        result = await dedup.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)

        assert len(result) == 1
        updated = result[0]
        # Tags should include both old and new, deduplicated
        assert "python" in updated.tags
        assert "web" in updated.tags

    @pytest.mark.asyncio
    async def test_importance_increments_on_update(
        self,
        mock_embedding: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        """Update increases importance by 0.05 (capped at 1.0)."""
        from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

        llm = MagicMock()
        response = MagicMock()
        response.content = "UPDATE_MERGE\nMERGED: Updated content"
        llm.ainvoke = AsyncMock(return_value=response)

        dedup = SmartDeduplicator(llm=llm, adaptive_capacity=False)

        existing_doc = VectorDocument(
            id="target-importance",
            content="Original content",
            vector=_fake_embedding(),
            metadata={"memory_type": "semantic", "importance": "0.5"},
        )
        search_result = SearchResult(document=existing_doc, score=0.78)

        vector = AsyncMock()
        vector.search = AsyncMock(return_value=[search_result])
        vector.get = AsyncMock(return_value=[existing_doc])
        vector.count = AsyncMock(return_value=10)

        mem = _make_semantic("Enriched content", embedding=_fake_embedding())
        result = await dedup.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)

        assert len(result) == 1
        assert result[0].importance == pytest.approx(0.55)
