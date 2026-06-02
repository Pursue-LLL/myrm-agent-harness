"""Tests for user-pinned memory protection.

Covers:
- BaseMemory.pinned default value
- ForgettingStrategy pinned immunity
- pin_memory / unpin_memory API
- Pinned round-trip through VectorDocument
- Pinned + importance combo (permanent equivalent)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import (
    doc_to_episodic,
    doc_to_semantic,
    episodic_to_doc,
    semantic_to_doc,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.strategies.forgetting import ForgettingStrategy
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory


class TestPinnedDefault:
    def test_semantic_default_false(self) -> None:
        m = SemanticMemory(content="test")
        assert m.pinned is False

    def test_episodic_default_false(self) -> None:
        m = EpisodicMemory(content="test")
        assert m.pinned is False

    def test_semantic_explicit_true(self) -> None:
        m = SemanticMemory(content="test", pinned=True)
        assert m.pinned is True


class TestForgettingPinnedImmunity:
    def test_pinned_not_forgotten(self) -> None:
        """Pinned memory should never be forgotten even with very low retention score."""
        strategy = ForgettingStrategy()
        m = SemanticMemory(
            content="critical knowledge",
            importance=0.01,
            access_count=0,
            created_at=datetime.now(UTC) - timedelta(days=365),
            pinned=True,
        )
        result = strategy.calculate_retention_score(m)
        assert not result.should_forget
        assert result.reason == "Protected: user-pinned"

    def test_unpinned_can_be_forgotten(self) -> None:
        """Unpinned memory with low score should be forgotten."""
        strategy = ForgettingStrategy()
        m = SemanticMemory(
            content="old knowledge",
            importance=0.01,
            access_count=0,
            created_at=datetime.now(UTC) - timedelta(days=365),
            pinned=False,
        )
        result = strategy.calculate_retention_score(m)
        assert result.should_forget

    def test_pinned_priority_over_other_checks(self) -> None:
        """Pinned check should come before min_retention_days check."""
        strategy = ForgettingStrategy()
        m = SemanticMemory(
            content="new but pinned",
            importance=0.01,
            access_count=0,
            created_at=datetime.now(UTC) - timedelta(days=365),
            pinned=True,
        )
        result = strategy.calculate_retention_score(m)
        assert result.reason == "Protected: user-pinned"


class TestDocRoundTrip:
    def test_semantic_pinned_roundtrip(self) -> None:
        m = SemanticMemory(content="test", pinned=True)
        doc = semantic_to_doc(m)
        assert doc.metadata["pinned"] is True
        restored = doc_to_semantic(doc)
        assert restored.pinned is True

    def test_semantic_unpinned_roundtrip(self) -> None:
        m = SemanticMemory(content="test", pinned=False)
        doc = semantic_to_doc(m)
        assert doc.metadata["pinned"] is False
        restored = doc_to_semantic(doc)
        assert restored.pinned is False

    def test_episodic_pinned_roundtrip(self) -> None:
        m = EpisodicMemory(content="event", pinned=True)
        doc = episodic_to_doc(m)
        assert doc.metadata["pinned"] is True
        restored = doc_to_episodic(doc)
        assert restored.pinned is True

    def test_legacy_doc_without_pinned(self) -> None:
        """Documents without pinned field should default to False."""
        doc = VectorDocument(
            id="d1",
            content="old data",
            embedding=[0.1],
            metadata={
                "memory_type": "semantic",
                "importance": 0.5,
                "confidence": 1.0,
            },
        )
        restored = doc_to_semantic(doc)
        assert restored.pinned is False


class TestDeletePinnedProtection:
    """Verify that pinned memories cannot be deleted when allow_pinned=False."""

    @pytest.mark.asyncio
    async def test_delete_memory_skips_pinned(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        pinned_doc = VectorDocument(
            id="m1",
            content="critical knowledge",
            embedding=[0.1],
            metadata={"user_id": "test_user", "memory_type": "semantic", "pinned": True},
        )
        mock_vector_store.get.return_value = [pinned_doc]

        mgr = MemoryManager(
            memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False
        )
        deleted = await mgr.delete_memory(memory_config.semantic_collection, ["m1"], allow_pinned=False)
        assert deleted == 0
        mock_vector_store.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_memory_allows_unpinned(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        unpinned_doc = VectorDocument(
            id="m2",
            content="normal knowledge",
            embedding=[0.1],
            metadata={"user_id": "test_user", "memory_type": "semantic", "pinned": False},
        )
        mock_vector_store.get.return_value = [unpinned_doc]
        mock_vector_store.delete.return_value = 1

        mgr = MemoryManager(
            memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False
        )
        deleted = await mgr.delete_memory(memory_config.semantic_collection, ["m2"], allow_pinned=False)
        assert deleted == 1

    @pytest.mark.asyncio
    async def test_delete_memory_default_allows_pinned(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        """Default allow_pinned=True: admin/WebUI path can delete pinned memories."""
        pinned_doc = VectorDocument(
            id="m1",
            content="critical knowledge",
            embedding=[0.1],
            metadata={"user_id": "test_user", "memory_type": "semantic", "pinned": True},
        )
        mock_vector_store.get.return_value = [pinned_doc]
        mock_vector_store.delete.return_value = 1

        mgr = MemoryManager(
            memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False
        )
        deleted = await mgr.delete_memory(memory_config.semantic_collection, ["m1"])
        assert deleted == 1

    @pytest.mark.asyncio
    async def test_delete_rule_skips_pinned(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_relational_store: AsyncMock,
    ) -> None:
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

        pinned_rule = ProceduralMemory(
            id="r1", content="When: X → Do: Y", trigger="X", action="Y", pinned=True
        )
        mock_relational_store.get_rule.return_value = pinned_rule

        mgr = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            relational=mock_relational_store,
            auto_warmup=False,
        )
        ok = await mgr.delete_rule("r1", allow_pinned=False)
        assert ok is False
        mock_relational_store.delete_rule.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_rule_allows_unpinned(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_relational_store: AsyncMock,
    ) -> None:
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

        unpinned_rule = ProceduralMemory(
            id="r2", content="When: A → Do: B", trigger="A", action="B", pinned=False
        )
        mock_relational_store.get_rule.return_value = unpinned_rule
        mock_relational_store.delete_rule.return_value = True

        mgr = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            relational=mock_relational_store,
            auto_warmup=False,
        )
        ok = await mgr.delete_rule("r2", allow_pinned=False)
        assert ok is True

    @pytest.mark.asyncio
    async def test_mixed_batch_only_deletes_unpinned(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        """When batch-deleting, only unpinned docs should be removed."""
        pinned_doc = VectorDocument(
            id="m1", content="pinned", embedding=[0.1],
            metadata={"user_id": "test_user", "memory_type": "semantic", "pinned": True},
        )
        unpinned_doc = VectorDocument(
            id="m2", content="normal", embedding=[0.1],
            metadata={"user_id": "test_user", "memory_type": "semantic", "pinned": False},
        )
        mock_vector_store.get.return_value = [pinned_doc, unpinned_doc]
        mock_vector_store.delete.return_value = 1

        mgr = MemoryManager(
            memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False
        )
        deleted = await mgr.delete_memory(memory_config.semantic_collection, ["m1", "m2"], allow_pinned=False)
        assert deleted == 1
        mock_vector_store.delete.assert_called_once_with(memory_config.semantic_collection, ["m2"])


class TestPinUnpinAPI:
    @pytest.mark.asyncio
    async def test_pin_memory(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        doc = VectorDocument(
            id="m1",
            content="test memory",
            embedding=[0.1],
            metadata={
                "user_id": "test_user",
                "memory_type": "semantic",
                "importance": 0.5,
                "confidence": 1.0,
                "pinned": False,
            },
        )
        mock_vector_store.get.return_value = [doc]

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False)
        result = await mgr.pin_memory("m1")
        assert result.pinned is True
        mock_vector_store.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_unpin_memory(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        doc = VectorDocument(
            id="m1",
            content="test memory",
            embedding=[0.1],
            metadata={
                "user_id": "test_user",
                "memory_type": "semantic",
                "importance": 0.5,
                "confidence": 1.0,
                "pinned": True,
            },
        )
        mock_vector_store.get.return_value = [doc]

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False)
        result = await mgr.unpin_memory("m1")
        assert result.pinned is False
        mock_vector_store.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_pin_already_pinned_is_noop(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        doc = VectorDocument(
            id="m1",
            content="test memory",
            embedding=[0.1],
            metadata={
                "user_id": "test_user",
                "memory_type": "semantic",
                "importance": 0.5,
                "confidence": 1.0,
                "pinned": True,
            },
        )
        mock_vector_store.get.return_value = [doc]

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False)
        result = await mgr.pin_memory("m1")
        assert result.pinned is True
        mock_vector_store.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_pin_not_found_raises(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        mock_vector_store.get.return_value = []

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False)
        from myrm_agent_harness.toolkits.memory._internal.storage import MemoryNotFoundError

        with pytest.raises(MemoryNotFoundError):
            await mgr.pin_memory("nonexistent")

    @pytest.mark.asyncio
    async def test_pin_wrong_user_raises(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        doc = VectorDocument(
            id="m1",
            content="test memory",
            embedding=[0.1],
            metadata={
                "user_id": "other-user",
                "memory_type": "semantic",
                "importance": 0.5,
                "confidence": 1.0,
                "pinned": False,
            },
        )
        mock_vector_store.get.return_value = [doc]

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False)
        from myrm_agent_harness.toolkits.memory._internal.storage import MemoryNotFoundError

        with pytest.raises(MemoryNotFoundError):
            await mgr.pin_memory("m1")

    @pytest.mark.asyncio
    async def test_pin_without_vector_backend_raises(
        self, memory_config: MemoryConfig, mock_embedding: AsyncMock
    ) -> None:
        mgr = MemoryManager(memory_config, user_id="test_user", vector=None, embedding=mock_embedding, auto_warmup=False)
        from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError

        with pytest.raises(MemoryError, match="Vector backend is required"):
            await mgr.pin_memory("m1")

    @pytest.mark.asyncio
    async def test_pin_episodic_memory(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        """Pin should also work for episodic memories (second collection)."""
        call_count = 0

        async def get_side_effect(collection: str, ids: list[str]) -> list[VectorDocument]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []
            return [
                VectorDocument(
                    id="e1",
                    content="event memory",
                    embedding=[0.1],
                    metadata={
                        "user_id": "test_user",
                        "memory_type": "episodic",
                        "importance": 0.5,
                        "confidence": 1.0,
                        "pinned": False,
                    },
                )
            ]

        mock_vector_store.get.side_effect = get_side_effect

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False)
        result = await mgr.pin_memory("e1")
        assert result.pinned is True
        mock_vector_store.upsert.assert_called_once()
