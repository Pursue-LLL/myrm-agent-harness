"""Deletion's derived-state cleanup, with the collaborators it must tolerate.

A deletion has to leave no derived trace behind: the claim graph, any exact-fact row and
the embedding cache all key off the memory's text. Those collaborators are optional and
differ between deployments, so the cleanup path is exercised here against each shape it
meets — a cache that can only evict one text at a time, a cache that cannot, an exact-fact
store that refuses, and a manager with no vector backend at all.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._manager.deletion import MemoryManagerDeletionMixin
from myrm_agent_harness.toolkits.memory.types import MemoryType
from myrm_agent_harness.toolkits.vector.base import VectorDocument

from .support import Embedder, manager_for, semantic, seed


class _EvictOnlyCache:
    """An embedding cache from before batch eviction existed: it can only drop one text."""

    def __init__(self) -> None:
        self.evicted: list[str] = []

    async def evict(self, text: str) -> bool:
        self.evicted.append(text)
        return True


class _FakeVectorlessManager(MemoryManagerDeletionMixin):
    """The mixin's own reads with no backend wired: they must answer empty, not raise."""

    _vector = None
    _embedding = None
    _relational = None
    _cache = None
    _graph = None
    _config = None
    _user_id = "u1"
    _namespaces = ["agent:default"]


def _doc(memory_id: str, content: str, *, pinned: bool = False) -> VectorDocument:
    return VectorDocument(
        id=memory_id,
        content=content,
        vector=[0.1, 0.2],
        metadata={"pinned": pinned, "primary_namespace": "agent:default", "namespaces": ["agent:default"]},
    )


class TestForgetDerived:
    async def test_a_cache_without_batch_eviction_drops_each_text_on_its_own(self) -> None:
        manager = _FakeVectorlessManager()
        cache = _EvictOnlyCache()
        manager._cache = cache  # type: ignore[assignment]

        await manager._forget_derived([_doc("m1", "first"), _doc("m2", "second")])

        assert cache.evicted == ["first", "second"]

    async def test_documents_without_text_are_not_offered_to_the_cache(self) -> None:
        manager = _FakeVectorlessManager()
        cache = _EvictOnlyCache()
        manager._cache = cache  # type: ignore[assignment]

        await manager._forget_derived([_doc("m1", ""), _doc("m2", "kept")])

        assert cache.evicted == ["kept"]

    async def test_an_exact_fact_store_that_refuses_does_not_stop_the_rest(self) -> None:
        manager = _FakeVectorlessManager()
        manager._relational = AsyncMock()  # type: ignore[assignment]
        manager._relational.delete_exact_fact = AsyncMock(side_effect=RuntimeError("unavailable"))  # type: ignore[attr-defined]

        await manager._forget_derived([_doc("m1", "text")])

        manager._relational.delete_exact_fact.assert_awaited_once_with("m1")  # type: ignore[attr-defined]


class TestReadsWithNoBackend:
    async def test_collecting_ids_without_a_vector_backend_reports_nothing(self) -> None:
        manager = _FakeVectorlessManager()

        assert await manager._collect_vector_ids("c", {}) == []

    async def test_collecting_documents_without_a_vector_backend_reports_nothing(self) -> None:
        manager = _FakeVectorlessManager()

        assert await manager._collect_vector_docs("c", {}) == []


class TestOwnedDocsFilter:
    async def test_pinned_documents_are_withheld_when_protection_is_on(self) -> None:
        manager = _FakeVectorlessManager()
        manager._vector = AsyncMock()  # type: ignore[assignment]
        manager._vector.get = AsyncMock(  # type: ignore[attr-defined]
            return_value=[_doc("m1", "free"), _doc("m2", "pinned", pinned=True)]
        )

        owned = await manager._owned_docs("c", ["m1", "m2"], allow_protected=False)

        assert [doc.id for doc in owned] == ["m1"]


class TestDeleteByIdReachesEveryModel:
    async def test_deleting_from_the_previous_model_drops_the_memory_everywhere(self, store, old_config, new_config) -> None:
        """Deleting reads the family by name: clearing the old collection also clears the current copy."""
        memory = semantic("Prefers tabs over spaces")
        await seed(store, old_config, semantics=[memory])
        manager = manager_for(store, new_config, Embedder(12))

        deleted = await manager.delete_memory(old_config.semantic_collection, [memory.id])

        assert deleted == 1
        assert await store.count(old_config.semantic_collection) == 0
        assert await store.count(new_config.semantic_collection) == 0
