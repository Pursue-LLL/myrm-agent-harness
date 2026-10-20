"""Shared scaffolding for tests that switch the embedding model over a real embedded Qdrant.

Mock stores cannot prove that a memory stays the same memory across a model switch (id,
owner scope, pin, tags, timestamps), that a deletion reaches the previous model's
collections, or how the BM25 sparse mirror collections behave, so these helpers build real
collections of two embedding dimensions and warm the mirror the way production does.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import store_episodics_batch, store_semantics_batch
from myrm_agent_harness.toolkits.memory._manager.reindex import _BATCH_SIZE
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemoryScope,
    SemanticMemory,
)
from myrm_agent_harness.toolkits.vector.base import VectorDocument, VectorStore

OLD_DIM = 8
NEW_DIM = 12
CREATED_AT = datetime(2025, 3, 1, 8, 30, tzinfo=UTC)


class Embedder:
    """Deterministic embedder whose vector length identifies the model that produced it."""

    def __init__(self, dim: int, *, fail_marker: str | None = None) -> None:
        self.dimension = dim
        self.embedded_texts: list[str] = []
        self.batch_sizes: list[int] = []
        self._fail_marker = fail_marker

    def vector_of(self, text: str) -> list[float]:
        return [float(len(text) % 5 + 1)] + [0.5] * (self.dimension - 1)

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._fail_marker is not None and any(self._fail_marker in t for t in texts):
            raise RuntimeError("embedding service unavailable")
        self.batch_sizes.append(len(texts))
        self.embedded_texts.extend(texts)
        return [self.vector_of(t) for t in texts]


class GatedEmbedder(Embedder):
    """Holds every embedding call until released, so a test can act while a page is in flight."""

    def __init__(self, dim: int) -> None:
        super().__init__(dim)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.entered.set()
        await self.release.wait()
        return await super().embed_batch(texts)


# Far above what a deletion needs, far below a model call that hangs.
_ACT_DEADLINE_S = 5


async def while_a_page_is_in_flight(
    manager: MemoryManager, gated: GatedEmbedder, act: Callable[[MemoryManager], Awaitable[object]]
):
    """Run ``act`` while the model call of a migration page is pending; it must finish without that call returning."""
    migration = asyncio.create_task(manager.reindex_from_orphans())
    await gated.entered.wait()
    try:
        await asyncio.wait_for(act(manager), timeout=_ACT_DEADLINE_S)
    finally:
        gated.release.set()
    return await migration


def unit(vector: list[float]) -> list[float]:
    """Cosine collections store unit vectors, so compare direction rather than raw values."""
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


def scope_of(agent: str) -> MemoryScope:
    return MemoryScope(primary_namespace=f"agent:{agent}", namespaces=["global", f"agent:{agent}"], agent_id=agent)


def semantic(content: str, *, agent: str = "default", **fields: object) -> SemanticMemory:
    return SemanticMemory(content=content, user_id="u1", scope=scope_of(agent), created_at=CREATED_AT, **fields)  # type: ignore[arg-type]


def episodic(content: str, *, agent: str = "default", **fields: object) -> EpisodicMemory:
    return EpisodicMemory(content=content, user_id="u1", scope=scope_of(agent), created_at=CREATED_AT, **fields)  # type: ignore[arg-type]


def manager_for(
    store: VectorStore,
    config: MemoryConfig,
    embedder: Embedder,
    *,
    graph: AsyncMock | None = None,
    namespaces: list[str] | None = None,
) -> MemoryManager:
    return MemoryManager(
        config,
        user_id="u1",
        vector=store,  # type: ignore[arg-type]
        embedding=embedder,  # type: ignore[arg-type]
        graph=graph,
        namespaces=namespaces,
    )


async def seed(
    store: VectorStore,
    config: MemoryConfig,
    *,
    semantics: list[SemanticMemory] | None = None,
    episodics: list[EpisodicMemory] | None = None,
    dim: int = OLD_DIM,
) -> None:
    """Write memories as a manager on ``config`` would, including its warm BM25 mirror collections."""
    embedder = Embedder(dim)
    if semantics:
        await store_semantics_batch(semantics, store, config, embedder, None)
    if episodics:
        await store_episodics_batch(episodics, store, config, embedder, None)
    await manager_for(store, config, embedder)._vector.bm25_backfill(config)  # type: ignore[union-attr]


async def scroll_all(store: VectorStore, collection: str) -> dict[str, VectorDocument]:
    documents: dict[str, VectorDocument] = {}
    cursor: str | None = None
    while True:
        page, cursor = await store.scroll(collection, limit=_BATCH_SIZE, offset=cursor)
        documents.update({doc.id: doc for doc in page})
        if cursor is None:
            return documents


async def held_by(store: VectorStore, collection: str) -> dict[str, VectorDocument]:
    """What a collection holds; one that was never created (nothing was written to it) holds nothing."""
    return await scroll_all(store, collection) if await store.collection_exists(collection) else {}


async def create_conversation_collection(store: VectorStore, name: str, dim: int) -> None:
    """Create the conversation collection the way ``memory.setup`` does: ``raw`` + ``summary`` named vectors."""
    await store.create_named_vector_collection(name, dim, names=("raw", "summary"))


def fail_on(
    monkeypatch: pytest.MonkeyPatch, store: VectorStore, method: str, collection: str, *, after_calls: int = 0
) -> None:
    """Make ``store.<method>`` raise for ``collection`` once ``after_calls`` calls succeeded (undone after the test)."""
    original: Callable[..., Awaitable[object]] = getattr(store, method)
    calls = 0

    async def flaky(name: str, *args: object, **kwargs: object) -> object:
        nonlocal calls
        if name == collection:
            calls += 1
            if calls > after_calls:
                raise RuntimeError(f"{method} failed")
        return await original(name, *args, **kwargs)

    monkeypatch.setattr(store, method, flaky)
