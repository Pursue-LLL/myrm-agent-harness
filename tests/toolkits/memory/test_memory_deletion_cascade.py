"""Tests for memory cascade deletion, cache eviction, and search exit barrier."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.embedding_cache import EmbeddingCache
from myrm_agent_harness.toolkits.memory._internal.search_service import MemorySearchService
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryStatus,
    MemoryType,
    SemanticMemory,
)


@pytest.fixture
def mock_embed_func():
    async def embed(text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    return embed


class TestEmbeddingCacheEviction:
    """Test evict and evict_batch on EmbeddingCache."""

    @pytest.mark.asyncio
    async def test_evict_single_text(self, mock_embed_func):
        cache = EmbeddingCache(embedding_func=mock_embed_func)
        text = "confidential password"
        await cache.get_embedding(text)
        assert await cache.get(text) is not None

        # Evict
        removed = await cache.evict(text)
        assert removed is True
        assert await cache.get(text) is None

        # Evict again returns False
        removed_again = await cache.evict(text)
        assert removed_again is False

    @pytest.mark.asyncio
    async def test_evict_batch_texts(self, mock_embed_func):
        cache = EmbeddingCache(embedding_func=mock_embed_func)
        texts = ["secret1", "secret2", "keep_me"]
        for t in texts:
            await cache.get_embedding(t)

        count = await cache.evict_batch(["secret1", "secret2", "not_exist"])
        assert count == 2
        assert await cache.get("secret1") is None
        assert await cache.get("secret2") is None
        assert await cache.get("keep_me") is not None


class TestSearchServiceExitBarrier:
    """Test that archived and disabled memories are blocked at search exit barrier."""

    def test_filter_results_blocks_archived_and_disabled(self):
        active_semantic = SemanticMemory(
            id="sem_1",
            content="Active fact",
            status=MemoryStatus.ACTIVE,
        )
        archived_semantic = SemanticMemory(
            id="sem_2",
            content="Soft deleted fact",
            status=MemoryStatus.ARCHIVED,
        )
        disabled_semantic = SemanticMemory(
            id="sem_3",
            content="Disabled fact",
            status=MemoryStatus.DISABLED,
        )
        active_episodic = EpisodicMemory(
            id="epi_1",
            content="Active event",
            status=MemoryStatus.ACTIVE,
        )
        archived_episodic = EpisodicMemory(
            id="epi_2",
            content="Archived event",
            status=MemoryStatus.ARCHIVED,
        )

        candidates = [
            MemorySearchResult(memory=active_semantic, score=0.9, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=archived_semantic, score=0.85, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=disabled_semantic, score=0.8, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=active_episodic, score=0.75, memory_type=MemoryType.EPISODIC),
            MemorySearchResult(memory=archived_episodic, score=0.7, memory_type=MemoryType.EPISODIC),
        ]

        filtered = MemorySearchService._filter_results(candidates)
        filtered_ids = [r.memory.id for r in filtered]

        assert "sem_1" in filtered_ids
        assert "epi_1" in filtered_ids
        assert "sem_2" not in filtered_ids
        assert "sem_3" not in filtered_ids
        assert "epi_2" not in filtered_ids
