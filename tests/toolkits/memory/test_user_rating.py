"""Tests for user_rating feedback learning system.

Covers:
- BaseMemory.user_rating field defaults and validation
- MemoryManager.rate_memory() EMA update logic
- SignalCalculator.rating_factor()
- Signal weight redistribution with rating dimension
- ForgettingStrategy rating_score integration
- Retriever _geometric_score rating dimension
- memory_manage rate action (Agent tool)
- Storage round-trip (to_doc / from_doc)
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.signals import (
    SignalCalculator,
    get_default_signal_weights,
)
from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
    ForgettingConfig,
    ForgettingStrategy,
)
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)

# ── BaseMemory field ───────────────────────────────────────────────


class TestUserRatingField:
    def test_default_neutral(self):
        mem = SemanticMemory(content="test", importance=0.5)
        assert mem.user_rating == 0.5

    def test_custom_value(self):
        mem = SemanticMemory(content="test", importance=0.5, user_rating=0.9)
        assert mem.user_rating == 0.9

    def test_clamped_to_bounds(self):
        mem = SemanticMemory(content="test", importance=0.5, user_rating=0.0)
        assert mem.user_rating == 0.0
        mem2 = SemanticMemory(content="test", importance=0.5, user_rating=1.0)
        assert mem2.user_rating == 1.0

    def test_episodic_has_rating(self):
        mem = EpisodicMemory(content="event", importance=0.5)
        assert mem.user_rating == 0.5


# ── SignalCalculator ───────────────────────────────────────────────


class TestRatingFactor:
    def test_returns_user_rating(self):
        mem = SemanticMemory(content="test", importance=0.5, user_rating=0.8)
        assert SignalCalculator.rating_factor(mem) == 0.8

    def test_default_when_missing(self):
        """Objects without user_rating attr should return 0.5."""

        class _Bare:
            pass

        assert SignalCalculator.rating_factor(_Bare()) == 0.5  # type: ignore[arg-type]

    def test_clamped_high(self):
        mem = SemanticMemory(content="test", importance=0.5, user_rating=1.0)
        assert SignalCalculator.rating_factor(mem) == 1.0


# ── Signal weights ─────────────────────────────────────────────────


class TestSignalWeights:
    @pytest.mark.parametrize(
        "mem_type", ["SEMANTIC", "EPISODIC", "PROFILE", "CLAIM", "PROCEDURAL"]
    )
    def test_weights_sum_to_one(self, mem_type: str):
        weights = get_default_signal_weights(mem_type)
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-6, f"{mem_type} weights sum to {total}"

    @pytest.mark.parametrize(
        "mem_type", ["SEMANTIC", "EPISODIC", "PROFILE", "CLAIM", "PROCEDURAL"]
    )
    def test_has_rating_weight(self, mem_type: str):
        weights = get_default_signal_weights(mem_type)
        assert "rating" in weights
        assert weights["rating"] > 0


# ── ForgettingStrategy ─────────────────────────────────────────────


class TestForgettingWithRating:
    def test_high_rating_improves_retention(self):
        strategy = ForgettingStrategy(ForgettingConfig())
        base = SemanticMemory(
            content="test",
            importance=0.1,
            access_count=0,
            user_rating=0.5,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        high_rated = base.model_copy(update={"user_rating": 1.0})
        low_rated = base.model_copy(update={"user_rating": 0.0})

        score_high = strategy.calculate_retention_score(high_rated)
        score_low = strategy.calculate_retention_score(low_rated)

        assert score_high.total_score > score_low.total_score
        assert score_high.rating_score == 1.0
        assert score_low.rating_score == 0.0

    def test_retention_score_has_rating(self):
        strategy = ForgettingStrategy(ForgettingConfig())
        mem = SemanticMemory(content="test", importance=0.5, user_rating=0.7)
        score = strategy.calculate_retention_score(mem)
        assert score.rating_score == 0.7

    def test_config_weights_sum_to_one(self):
        cfg = ForgettingConfig()
        total = (
            cfg.time_weight
            + cfg.access_weight
            + cfg.importance_weight
            + cfg.relation_weight
            + cfg.rating_weight
        )
        assert abs(total - 1.0) < 1e-6


# ── Retriever geometric score ─────────────────────────────────────


class TestRetrieverRatingDimension:
    def test_high_rating_boosts_score(self):
        retriever = MemoryRetriever()
        base_mem = SemanticMemory(content="test", importance=0.5, user_rating=0.5)
        high_mem = base_mem.model_copy(update={"user_rating": 1.0})
        low_mem = base_mem.model_copy(update={"user_rating": 0.1})

        base_result = MemorySearchResult(
            memory=base_mem, score=0.8, memory_type=MemoryType.SEMANTIC
        )
        high_result = MemorySearchResult(
            memory=high_mem, score=0.8, memory_type=MemoryType.SEMANTIC
        )
        low_result = MemorySearchResult(
            memory=low_mem, score=0.8, memory_type=MemoryType.SEMANTIC
        )

        score_base = retriever._geometric_score(0.8, base_result)
        score_high = retriever._geometric_score(0.8, high_result)
        score_low = retriever._geometric_score(0.8, low_result)

        assert score_high > score_base
        assert score_base > score_low


# ── MemoryManager.rate_memory() ────────────────────────────────────


class TestRateMemory:
    @pytest.mark.asyncio
    async def test_rate_memory_positive_uses_alpha(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        doc = VectorDocument(
            id="mem-1",
            content="test",
            vector=[0.1] * 768,
            metadata={"user_id": "test_user", "user_rating": 0.5},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.get.return_value = [doc]
        mock_vector_store.collection_exists = AsyncMock(return_value=True)

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        ok = await manager.rate_memory("mem-1", 5)
        assert ok is True

        upserted_docs = mock_vector_store.upsert.call_args[0][1]
        new_rating = upserted_docs[0].metadata["user_rating"]
        # Positive: normalized=1.0 >= old=0.5 → alpha_positive=0.3
        # EMA: 0.5 + 0.3 * (1.0 - 0.5) = 0.65
        assert abs(new_rating - 0.65) < 0.01

    @pytest.mark.asyncio
    async def test_rate_memory_negative_uses_alpha_negative(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        doc = VectorDocument(
            id="mem-1",
            content="test",
            vector=[0.1] * 768,
            metadata={"user_id": "test_user", "user_rating": 0.5},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.get.return_value = [doc]
        mock_vector_store.collection_exists = AsyncMock(return_value=True)

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        ok = await manager.rate_memory("mem-1", 1)
        assert ok is True

        upserted_docs = mock_vector_store.upsert.call_args[0][1]
        new_rating = upserted_docs[0].metadata["user_rating"]
        # Negative: normalized=0.0 < old=0.5 → alpha_negative=0.5
        # EMA: 0.5 + 0.5 * (0.0 - 0.5) = 0.25
        assert abs(new_rating - 0.25) < 0.01

    @pytest.mark.asyncio
    async def test_asymmetric_recovery_requires_more_positives(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        """A memory downgraded by one negative needs multiple positives to recover."""
        doc = VectorDocument(
            id="mem-1",
            content="test",
            vector=[0.1] * 768,
            metadata={"user_id": "test_user", "user_rating": 0.5},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.get.return_value = [doc]
        mock_vector_store.collection_exists = AsyncMock(return_value=True)

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        # One negative: 0.5 → 0.25
        await manager.rate_memory("mem-1", 1)
        after_neg = mock_vector_store.upsert.call_args[0][1][0].metadata["user_rating"]

        # One positive: 0.25 + 0.3*(1.0-0.25) = 0.475
        doc.metadata["user_rating"] = after_neg
        mock_vector_store.get.return_value = [doc]
        await manager.rate_memory("mem-1", 5)
        after_one_pos = mock_vector_store.upsert.call_args[0][1][0].metadata[
            "user_rating"
        ]

        # Still below neutral after one positive recovery
        assert after_one_pos < 0.5

    @pytest.mark.asyncio
    async def test_rate_memory_not_found(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        mock_vector_store.get.return_value = []

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        ok = await manager.rate_memory("nonexistent", 3)
        assert ok is False

    @pytest.mark.asyncio
    async def test_rate_memory_wrong_user(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        doc = VectorDocument(
            id="mem-1",
            content="test",
            vector=[0.1] * 768,
            metadata={"user_id": "other_user", "user_rating": 0.5},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.get.return_value = [doc]

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        ok = await manager.rate_memory("mem-1", 5)
        assert ok is False

    @pytest.mark.asyncio
    async def test_rate_memory_explicit_collection(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        """When collection is explicitly passed, only that collection is searched."""
        doc = VectorDocument(
            id="mem-1",
            content="test",
            vector=[0.1] * 768,
            metadata={"user_id": "test_user", "user_rating": 0.5},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.get.return_value = [doc]
        mock_vector_store.collection_exists = AsyncMock(return_value=True)

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        ok = await manager.rate_memory("mem-1", 4, collection="custom_collection")
        assert ok is True
        mock_vector_store.get.assert_called_once_with("custom_collection", ["mem-1"])

    @pytest.mark.asyncio
    async def test_rate_memory_clamped_score(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        """Scores outside [1,5] are clamped."""
        doc = VectorDocument(
            id="mem-1",
            content="test",
            vector=[0.1] * 768,
            metadata={"user_id": "test_user", "user_rating": 0.5},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.get.return_value = [doc]
        mock_vector_store.collection_exists = AsyncMock(return_value=True)

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        # Score 10 should be clamped to 5 → normalized=1.0
        ok = await manager.rate_memory("mem-1", 10)
        assert ok is True
        new_rating = mock_vector_store.upsert.call_args[0][1][0].metadata["user_rating"]
        # Same as score=5: 0.5 + 0.3*(1.0-0.5) = 0.65
        assert abs(new_rating - 0.65) < 0.01

    @pytest.mark.asyncio
    async def test_rate_memory_no_user_id_in_doc(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        """When doc has no user_id (single-tenant), rate should still succeed."""
        doc = VectorDocument(
            id="mem-1",
            content="test",
            vector=[0.1] * 768,
            metadata={"user_rating": 0.5},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.get.return_value = [doc]
        mock_vector_store.collection_exists = AsyncMock(return_value=True)

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        ok = await manager.rate_memory("mem-1", 4)
        assert ok is True

    @pytest.mark.asyncio
    async def test_rate_memory_vector_exception(
        self, mock_vector_store, mock_embedding, memory_config
    ):
        """When vector.get raises, rate_memory should continue to next collection."""
        mock_vector_store.get.side_effect = RuntimeError("connection lost")
        mock_vector_store.collection_exists = AsyncMock(return_value=True)

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        ok = await manager.rate_memory("mem-1", 5)
        assert ok is False

    @pytest.mark.asyncio
    async def test_rate_memory_no_vector(self, mock_embedding, memory_config):
        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            embedding=mock_embedding,
            auto_warmup=False,
        )

        ok = await manager.rate_memory("mem-1", 5)
        assert ok is False


# ── Storage round-trip ─────────────────────────────────────────────


class TestStorageRoundTrip:
    def test_semantic_to_doc_includes_rating(self):
        from myrm_agent_harness.toolkits.memory._internal.storage import semantic_to_doc

        mem = SemanticMemory(content="test", importance=0.5, user_rating=0.8)
        doc = semantic_to_doc(mem)
        assert doc.metadata["user_rating"] == 0.8

    def test_doc_to_semantic_restores_rating(self):
        from myrm_agent_harness.toolkits.memory._internal.storage import doc_to_semantic

        doc = VectorDocument(
            id="mem-1",
            content="test",
            vector=[0.1] * 3,
            metadata={
                "memory_type": "semantic",
                "importance": 0.5,
                "confidence": 1.0,
                "user_rating": 0.75,
                "access_count": 0,
            },
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mem = doc_to_semantic(doc)
        assert mem.user_rating == 0.75

    def test_doc_to_semantic_default_when_missing(self):
        from myrm_agent_harness.toolkits.memory._internal.storage import doc_to_semantic

        doc = VectorDocument(
            id="mem-1",
            content="test",
            vector=[0.1] * 3,
            metadata={
                "memory_type": "semantic",
                "importance": 0.5,
                "confidence": 1.0,
                "access_count": 0,
            },
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mem = doc_to_semantic(doc)
        assert mem.user_rating == 0.5

    def test_episodic_to_doc_includes_rating(self):
        from myrm_agent_harness.toolkits.memory._internal.storage import episodic_to_doc

        mem = EpisodicMemory(content="event", importance=0.5, user_rating=0.3)
        doc = episodic_to_doc(mem)
        assert doc.metadata["user_rating"] == 0.3

    def test_doc_to_episodic_restores_rating(self):
        from myrm_agent_harness.toolkits.memory._internal.storage import doc_to_episodic

        doc = VectorDocument(
            id="mem-1",
            content="event",
            vector=[0.1] * 3,
            metadata={
                "memory_type": "episodic",
                "event_type": "conversation",
                "importance": 0.5,
                "user_rating": 0.9,
                "access_count": 0,
            },
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mem = doc_to_episodic(doc)
        assert mem.user_rating == 0.9


# ── Cited Memory ID Cache (10.3 auto-feedback) ───────────────────────


class TestCitedMemoryIdCache:
    """Test MemoryManager.last_cited_memory_ids lifecycle."""

    @staticmethod
    def _make_manager(cfg: MemoryConfig) -> MemoryManager:
        vector = AsyncMock()
        vector.collection_exists = AsyncMock(return_value=True)
        return MemoryManager(cfg, user_id="test_user", vector=vector, auto_warmup=False)

    def test_default_empty(self, memory_config):
        mgr = self._make_manager(memory_config)
        assert mgr.last_cited_memory_ids == []

    def test_set_and_get(self, memory_config):
        mgr = self._make_manager(memory_config)
        mgr.set_last_cited_memory_ids(["m1", "m2"])
        assert mgr.last_cited_memory_ids == ["m1", "m2"]

    def test_overwrite(self, memory_config):
        mgr = self._make_manager(memory_config)
        mgr.set_last_cited_memory_ids(["m1"])
        mgr.set_last_cited_memory_ids(["m3", "m4"])
        assert mgr.last_cited_memory_ids == ["m3", "m4"]

    def test_clear(self, memory_config):
        mgr = self._make_manager(memory_config)
        mgr.set_last_cited_memory_ids(["m1"])
        mgr.set_last_cited_memory_ids([])
        assert mgr.last_cited_memory_ids == []

    def test_begin_session_clears_cache(self, memory_config):
        mgr = self._make_manager(memory_config)
        mgr.set_last_cited_memory_ids(["m1", "m2"])
        mgr.begin_session("chat-1")
        assert mgr.last_cited_memory_ids == []

    def test_begin_session_clears_even_with_active_session(self, memory_config):
        mgr = self._make_manager(memory_config)
        mgr.begin_session("chat-1")
        mgr.set_last_cited_memory_ids(["m5"])
        mgr.begin_session("chat-2")
        assert mgr.last_cited_memory_ids == []
