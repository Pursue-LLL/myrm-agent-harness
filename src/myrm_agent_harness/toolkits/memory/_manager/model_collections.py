"""Per-embedding-model memory collections: which one is current, which a model switch left behind.

[INPUT]
- memory.config::MemoryConfig (POS: per-model collection naming)
- memory.types::MemoryType (POS: memory taxonomy)
- memory._internal.bm25_sparse_index::{BM25_COLLECTION_SUFFIX, bm25_collection_for, unwrap_sparse_mirror} (POS: sparse mirror naming and the backend beneath it)
- vector.base::VectorStore (POS: collection listing / counting / dropping)

[OUTPUT]
- ModelCollection: a memory collection of one embedding model
- current_collection / previous_model_collections / memory_collections: which collections hold memories
- catalog_of: the backend that can list collections
- retire_if_drained: drop an emptied previous-model collection
- drop_from_previous_models: remove deleted memory ids from the previous models' collections
- family_lock: serialises migration steps against deletions of the same collection family

[POS]
Collections are named ``{prefix}_{type}_{model}``, so a model switch leaves the previous model's
memories in collections the current model never reads. The reindex migration and every deletion
read that naming through this one module: a deletion reaches the memories a switch left
behind, and a sparse ``_bm25`` mirror is never mistaken for a model's collection. A migration page
is read, re-embedded and written over several awaits, so a deletion landing in between would be
undone by that page; the page therefore settles under the family lock (never across the embedding
call) and every deletion takes it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_index import (
    BM25_COLLECTION_SUFFIX,
    bm25_collection_for,
    unwrap_sparse_mirror,
)
from myrm_agent_harness.toolkits.memory.types import MemoryType
from myrm_agent_harness.toolkits.vector.base import VectorStore

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)

_VECTOR_TYPES = (MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.CONVERSATION)

# One lock per (backend, collection prefix); managers are built per request, the backend is shared.
_family_locks: dict[tuple[int, str], asyncio.Lock] = {}


@dataclass(frozen=True)
class ModelCollection:
    """A memory collection that belongs to one embedding model."""

    name: str
    memory_type: MemoryType
    model_suffix: str


def current_collection(config: MemoryConfig, memory_type: MemoryType) -> str:
    """The current model's collection for a vector-backed memory type."""
    if memory_type is MemoryType.SEMANTIC:
        return config.semantic_collection
    if memory_type is MemoryType.EPISODIC:
        return config.episodic_collection
    if memory_type is MemoryType.CONVERSATION:
        return config.conversation_collection
    raise ValueError(f"{memory_type.value} memories are not stored in a vector collection")


def previous_model_collections(names: Iterable[str], config: MemoryConfig) -> list[ModelCollection]:
    """The collections among ``names`` that hold memories of another embedding model than ``config``'s.

    Only ``{prefix}_{type}_{model}`` names count: a sparse mirror (``{collection}_bm25``) shares the
    prefix but merely indexes its dense collection, and another prefix is not this manager's.
    """
    current = {current_collection(config, memory_type) for memory_type in _VECTOR_TYPES}
    found: list[ModelCollection] = []
    for name in sorted(names):
        if name in current or name.endswith(BM25_COLLECTION_SUFFIX):
            continue
        for memory_type in _VECTOR_TYPES:
            head = f"{config.collection_prefix}_{memory_type.value}_"
            if name.startswith(head) and len(name) > len(head):
                found.append(ModelCollection(name=name, memory_type=memory_type, model_suffix=name[len(head) :]))
                break
    return found


def catalog_of(vector: VectorStoreProtocol | None) -> VectorStore | None:
    """Backend that can list collections.

    The manager's vector store is wrapped by the BM25 mirror, whose protocol surface has no
    collection listing, so look beneath it.
    """
    if vector is None:
        return None
    backend = unwrap_sparse_mirror(vector)
    return backend if isinstance(backend, VectorStore) else None


async def memory_collections(vector: VectorStoreProtocol | None, config: MemoryConfig) -> dict[MemoryType, list[str]]:
    """Every collection holding memories, per type: the current model's first, then previous models'.

    A backend that cannot list collections reports the current model's names only; a listing
    backend reports only collections that exist, so a bulk deletion never trips over a missing one.
    """
    current = {memory_type: current_collection(config, memory_type) for memory_type in _VECTOR_TYPES}
    catalog = catalog_of(vector)
    if catalog is None:
        return {memory_type: [name] for memory_type, name in current.items()}
    try:
        listed = await catalog.list_collections()
    except Exception as e:
        logger.warning("Failed to list collections, covering the current model only: %s", e)
        return {memory_type: [name] for memory_type, name in current.items()}
    present = set(listed)
    previous = previous_model_collections(listed, config)
    return {
        memory_type: [name for name in [current[memory_type]] if name in present]
        + [c.name for c in previous if c.memory_type is memory_type]
        for memory_type in _VECTOR_TYPES
    }


async def retire_if_drained(vector: VectorStoreProtocol | None, collection: str) -> None:
    """Drop an emptied previous-model collection together with its sparse mirror.

    Never pass the current model's collection. A collection that still holds memories is left alone.
    """
    catalog = catalog_of(vector)
    if catalog is None:
        return
    try:
        if await catalog.count(collection) > 0:
            return
        await catalog.delete_collection(collection)
        await catalog.delete_collection(bm25_collection_for(collection))
    except Exception as e:
        logger.warning("Could not drop the emptied collection %s: %s", collection, e)


async def drop_from_previous_models(
    vector: VectorStoreProtocol | None, config: MemoryConfig, collection: str, ids: list[str]
) -> list[str]:
    """Remove ``ids`` from the previous models' collections that hold the same kind of memory as ``collection``.

    ``collection`` is a current model's collection (any other name has no previous copies). Every
    previous collection is attempted and the ones that could not be cleared are returned; one this
    emptied is dropped. Call under ``family_lock``.
    """
    memory_type = next((t for t in _VECTOR_TYPES if current_collection(config, t) == collection), None)
    if vector is None or memory_type is None or not ids:
        return []
    failed: list[str] = []
    for name in (await memory_collections(vector, config))[memory_type]:
        if name == collection:
            continue
        try:
            await vector.delete(name, ids)
            await retire_if_drained(vector, name)
        except Exception as e:
            logger.warning("Could not remove deleted memories from %s: %s", name, e)
            failed.append(name)
    return failed


def family_lock(vector: VectorStoreProtocol | None, config: MemoryConfig) -> asyncio.Lock:
    """The lock every migration step and deletion of one collection family runs under.

    A migration page reads the previous model's memories, is embedded, then writes them into the
    current collection. A deletion that lands in between must not be undone by that write, so the
    page re-checks what it read under this lock, and every deletion takes it. It is never held
    across the embedding call: holders do vector-store reads and writes only. ``asyncio.Lock`` is
    not re-entrant, so code already inside it must call the unlocked internals.
    """
    key = (id(catalog_of(vector) or vector), config.collection_prefix)
    lock = _family_locks.get(key)
    if lock is None:
        lock = _family_locks[key] = asyncio.Lock()
    return lock
