"""MemoryManager reindex mixin — carries memories over after an embedding-model switch.

[INPUT]
- memory.config::MemoryConfig (POS: per-model collection naming)
- memory._internal.storage::{embed_batch, doc_to_conversation, store_conversations_batch} (POS: cached batch embedding, dual-vector conversation writer)
- memory._internal.bm25_sparse_index::unwrap_sparse_mirror (POS: backend beneath the BM25 mirror)
- vector.base::VectorStore (POS: collection listing / counting)

[OUTPUT]
- OrphanCollectionInfo, ReindexEstimate, ReindexResult, ProgressCallback: reindex data types
- MemoryManagerReindexMixin: detect_orphan_collections, estimate_reindex, reindex_from_orphans

[POS]
Collections are named per embedding model, so switching models leaves the old
memories unreachable. Detection lists the previous models' collections; migration
copies each memory (same id, payload, owner scope) into the current model's
collection with a freshly embedded vector. Old collections are preserved.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_index import unwrap_sparse_mirror
from myrm_agent_harness.toolkits.memory._internal.storage import (
    doc_to_conversation,
    embed_batch,
    store_conversations_batch,
)
from myrm_agent_harness.toolkits.vector.base import VectorDocument, VectorStore

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)

_COLLECTION_PREFIXES = ("_semantic_", "_episodic_", "_conversation_")

# Memories read, de-duplicated against the current collection and embedded per round trip.
_BATCH_SIZE = 100


@dataclass(frozen=True)
class OrphanCollectionInfo:
    """Describes a collection orphaned by a model switch."""

    collection_name: str
    memory_type: str
    old_model_suffix: str
    document_count: int


@dataclass(frozen=True)
class ReindexEstimate:
    """Cost estimate for re-embedding orphan memories."""

    total_memories: int
    orphan_collections: list[OrphanCollectionInfo]


@dataclass(frozen=True)
class ReindexResult:
    """Outcome of a reindex run, counted per memory.

    ``migrated`` memories were re-embedded into the current model's collection,
    ``skipped`` ones were already there (or have no text to embed), and ``failed``
    ones could not be read, embedded or written; they migrate on the next run.
    """

    migrated: int
    skipped: int
    failed: int


ProgressCallback = Callable[[int, int, str], None]


def _extract_model_suffix(collection_name: str, prefix: str) -> str | None:
    """Extract the model suffix from a collection name after a known prefix infix."""
    idx = collection_name.find(prefix)
    if idx == -1:
        return None
    return collection_name[idx + len(prefix) :]


@dataclass
class _Tally:
    """Mutable per-run counters."""

    migrated: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def done(self) -> int:
        return self.migrated + self.skipped + self.failed


class MemoryManagerReindexMixin:
    """Mixin providing orphan collection detection and migration."""

    _config: MemoryConfig
    _vector: VectorStoreProtocol | None
    _cache: EmbeddingCacheProtocol | None

    def _catalog(self) -> VectorStore | None:
        """Backend that can list collections.

        The manager's vector store is wrapped by the BM25 mirror, whose protocol
        surface has no collection listing / info, so look beneath it.
        """
        if self._vector is None:
            return None
        backend = unwrap_sparse_mirror(self._vector)
        return backend if isinstance(backend, VectorStore) else None

    async def detect_orphan_collections(self) -> list[OrphanCollectionInfo]:
        """Detect collections left behind by previous embedding models.

        Collections that match our prefix but are not one of the current model's
        three collections, and still hold memories, are orphans.
        """
        catalog = self._catalog()
        if catalog is None:
            return []

        config = self._config
        current_collections = {
            config.semantic_collection,
            config.episodic_collection,
            config.conversation_collection,
        }
        prefix = config.collection_prefix

        try:
            all_collections = await catalog.list_collections()
        except Exception as e:
            logger.warning("Failed to list collections for orphan detection: %s", e)
            return []

        orphans: list[OrphanCollectionInfo] = []
        for name in all_collections:
            if not name.startswith(prefix):
                continue
            if name in current_collections:
                continue

            memory_type = ""
            model_suffix = ""
            for infix in _COLLECTION_PREFIXES:
                suffix = _extract_model_suffix(name, infix)
                if suffix is not None:
                    memory_type = infix.strip("_")
                    model_suffix = suffix
                    break

            if not memory_type:
                continue

            try:
                # Not get_collection_info: it cannot describe named-vector (conversation) collections.
                count = await catalog.count(name)
            except Exception:
                count = 0

            if count == 0:
                continue

            orphans.append(
                OrphanCollectionInfo(
                    collection_name=name,
                    memory_type=memory_type,
                    old_model_suffix=model_suffix,
                    document_count=count,
                )
            )

        return orphans

    async def estimate_reindex(self) -> ReindexEstimate:
        """Estimate the scope of a reindex operation without executing it."""
        orphans = await self.detect_orphan_collections()
        total = sum(o.document_count for o in orphans)
        return ReindexEstimate(total_memories=total, orphan_collections=orphans)

    async def reindex_from_orphans(
        self,
        *,
        progress_cb: ProgressCallback | None = None,
    ) -> ReindexResult:
        """Re-embed memories from orphan collections into the current model's collections.

        Each memory keeps its id and payload (owner scope, pin, importance,
        timestamps) and only its vector is recomputed, so memories that already
        exist in the current collection are skipped and re-running is cheap.
        Old collections are preserved as a safety net.

        Args:
            progress_cb: Optional callback(done, total, phase) for progress reporting.

        Raises:
            MemoryError: When orphans exist but vector + embedding backends are not both configured.
        """
        orphans = await self.detect_orphan_collections()
        if not orphans:
            return ReindexResult(migrated=0, skipped=0, failed=0)
        self._vec()  # type: ignore[attr-defined]  # fail fast before touching any collection

        total = sum(o.document_count for o in orphans)
        tally = _Tally()

        def report(phase: str) -> None:
            if progress_cb:
                progress_cb(tally.done, total, phase)

        report("starting")
        for orphan in orphans:
            await self._migrate_orphan(orphan, tally, lambda: report("migrating"))
        if progress_cb:
            progress_cb(total, total, "completed")

        logger.info(
            "Reindex completed: migrated=%d, skipped=%d, failed=%d",
            tally.migrated,
            tally.skipped,
            tally.failed,
        )
        return ReindexResult(migrated=tally.migrated, skipped=tally.skipped, failed=tally.failed)

    async def _migrate_orphan(self, orphan: OrphanCollectionInfo, tally: _Tally, on_batch: Callable[[], None]) -> None:
        """Page through one orphan collection; an unreadable remainder counts as failed."""
        vector, _ = self._vec()  # type: ignore[attr-defined]
        cursor: str | None = None
        read = 0
        while True:
            try:
                documents, cursor = await vector.scroll(orphan.collection_name, limit=_BATCH_SIZE, offset=cursor)
            except Exception as e:
                unread = max(orphan.document_count - read, 0)
                logger.warning(
                    "Reindex cannot read %s, %d memories not migrated: %s", orphan.collection_name, unread, e
                )
                tally.failed += unread
                on_batch()
                return
            read += len(documents)
            if documents:
                await self._migrate_batch(orphan.memory_type, documents, tally)
                on_batch()
            if not documents or cursor is None:
                return

    async def _migrate_batch(self, memory_type: str, documents: list[VectorDocument], tally: _Tally) -> None:
        """Migrate one page; counts are applied only once the whole page settled."""
        candidates = [d for d in documents if d.content.strip()]
        tally.skipped += len(documents) - len(candidates)
        if not candidates:
            return
        target = self._target_collection(memory_type)
        try:
            missing = await self._missing_from(target, candidates)
            if missing:
                await self._write_migrated(memory_type, target, missing)
        except Exception as e:
            logger.warning("Reindex failed for %d %s memories: %s", len(candidates), memory_type, e)
            tally.failed += len(candidates)
            return
        tally.skipped += len(candidates) - len(missing)
        tally.migrated += len(missing)

    def _target_collection(self, memory_type: str) -> str:
        return {
            "semantic": self._config.semantic_collection,
            "episodic": self._config.episodic_collection,
            "conversation": self._config.conversation_collection,
        }[memory_type]

    async def _missing_from(self, target: str, documents: list[VectorDocument]) -> list[VectorDocument]:
        """Documents whose id is not in ``target`` yet (memories written since the switch win)."""
        vector, _ = self._vec()  # type: ignore[attr-defined]
        if not await vector.collection_exists(target):
            return documents
        present, _ = await vector.scroll(
            target, limit=len(documents), filters={"id": {"$in": [d.id for d in documents]}}
        )
        present_ids = {d.id for d in present}
        return [d for d in documents if d.id not in present_ids]

    async def _write_migrated(self, memory_type: str, target: str, documents: list[VectorDocument]) -> None:
        """Write ``documents`` into the current model's collection with new-model vectors.

        Semantic and episodic memories are copied verbatim (payload carries every
        persisted field) so nothing depends on model round-tripping. Conversations
        go through their dual-vector writer, which owns the raw / summary layout.
        Vectors are never carried over: they belong to the old model.
        """
        vector, embedding = self._vec()  # type: ignore[attr-defined]
        if memory_type == "conversation":
            conversations = [doc_to_conversation(d, include_raw=True, config=self._config) for d in documents]
            for conversation in conversations:
                conversation.raw_embedding = None
                conversation.summary_embedding = None
            await store_conversations_batch(conversations, vector, self._config, embedding, self._cache)
            return
        vectors = await embed_batch([d.content for d in documents], embedding, self._cache)
        await vector.upsert(
            target, [d.model_copy(update={"vector": fresh}) for d, fresh in zip(documents, vectors, strict=True)]
        )
