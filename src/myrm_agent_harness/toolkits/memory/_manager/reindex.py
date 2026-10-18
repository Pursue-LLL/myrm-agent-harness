"""MemoryManager reindex mixin — carries memories over after an embedding-model switch.

[INPUT]
- memory.config::MemoryConfig (POS: per-model collection naming)
- memory._internal.storage::{embed_batch, embed_conversations, doc_to_conversation, store_conversations_batch} (POS: cached batch embedding, dual-vector conversation embedder and writer)
- memory._manager.model_collections::{catalog_of, current_collection, family_lock, orphan_mirror_collections, previous_model_collections, retire_if_drained} (POS: per-model collection naming, retirement and the lock shared with deletions)
- vector.base::VectorDocument (POS: scrolled memory documents)

[OUTPUT]
- OrphanCollectionInfo, ReindexEstimate, ReindexResult, ProgressCallback: reindex data types
- MemoryManagerReindexMixin: detect_orphan_collections, estimate_reindex, reindex_from_orphans

[POS]
Collections are named per embedding model, so switching models leaves the old
memories unreachable. Detection lists the previous models' collections; migration
moves each memory (same id, payload, owner scope) into the current model's
collection with a freshly embedded vector and removes it from the old collection
once the current one is read back to hold it. An emptied old collection is dropped.
A keyword-mode mirror whose dense collection never existed is detected and migrated
the same way: the mirror's payload matches the dense layout, so the page re-embeds
into the current collection and the drained mirror is retired.
A page is read and settled under the collection family's lock but embedded outside it: the
model call is slow and can hang, and a deletion must not queue behind it. Settling re-checks
what the page read, so a memory a deletion removed meanwhile is not written back (and not counted
as failed), and a copy that reached the current collection meanwhile is never overwritten.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.storage import (
    doc_to_conversation,
    embed_batch,
    embed_conversations,
    store_conversations_batch,
)
from myrm_agent_harness.toolkits.memory._manager.model_collections import (
    catalog_of,
    current_collection,
    family_lock,
    orphan_mirror_collections,
    previous_model_collections,
    retire_if_drained,
)
from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemoryType
from myrm_agent_harness.toolkits.vector.base import VectorDocument

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)

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
    ones could not be read, embedded, written or removed from the old collection;
    they move on the next run. Every counted memory except ``failed`` has left the old collection.
    """

    migrated: int
    skipped: int
    failed: int


ProgressCallback = Callable[[int, int, str], None]


@dataclass
class _Tally:
    """Mutable per-run counters."""

    migrated: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def done(self) -> int:
        return self.migrated + self.skipped + self.failed


@dataclass(frozen=True)
class _Embedded:
    """The memories of a page the current model embedded, ready to be written without another model call."""

    documents: dict[str, VectorDocument] = field(default_factory=dict)
    conversations: dict[str, ConversationMemory] = field(default_factory=dict)

    def __contains__(self, memory_id: object) -> bool:
        return memory_id in self.documents or memory_id in self.conversations


class MemoryManagerReindexMixin:
    """Mixin providing orphan collection detection and migration."""

    _config: MemoryConfig
    _vector: VectorStoreProtocol | None
    _cache: EmbeddingCacheProtocol | None

    async def detect_orphan_collections(self) -> list[OrphanCollectionInfo]:
        """Detect collections left behind by previous embedding models.

        Collections of another model than the current one that still hold memories are orphans.
        A keyword-mode mirror whose dense collection never existed counts too: once an embedding
        model is configured, its memories are reachable through neither the dense reads nor the
        BM25 fan-out (which queries the current model's mirror), so the migration has to carry
        them over.
        """
        catalog = catalog_of(self._vector)
        if catalog is None:
            return []

        try:
            listed = await catalog.list_collections()
        except Exception as e:
            logger.warning("Failed to list collections for orphan detection: %s", e)
            return []
        previous = previous_model_collections(listed, self._config) + orphan_mirror_collections(listed, self._config)

        orphans: list[OrphanCollectionInfo] = []
        for collection in previous:
            try:
                # Not get_collection_info: it cannot describe named-vector (conversation) collections.
                count = await catalog.count(collection.name)
            except Exception as e:
                logger.warning("Could not count %s, leaving it out of the migration estimate: %s", collection.name, e)
                count = 0
            if count == 0:
                continue
            orphans.append(
                OrphanCollectionInfo(
                    collection_name=collection.name,
                    memory_type=collection.memory_type.value,
                    old_model_suffix=collection.model_suffix,
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
        """Move memories from orphan collections into the current model's collections.

        Each memory keeps its id and payload (owner scope, pin, importance,
        timestamps) and only its vector is recomputed, so memories that already
        exist in the current collection are not embedded again. A memory leaves
        the old collection only after the current one is read back to hold it,
        and an emptied old collection is dropped; whatever failed stays for the next run.

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
            async with family_lock(self._vector, self._config):
                if not await vector.collection_exists(orphan.collection_name):
                    return  # a bulk deletion removed it: nothing left to move, and nothing failed
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
                await self._migrate_page(orphan, documents, tally)
                on_batch()
            if not documents or cursor is None:
                async with family_lock(self._vector, self._config):
                    if await vector.collection_exists(orphan.collection_name):
                        await retire_if_drained(self._vector, orphan.collection_name)
                return

    async def _migrate_page(self, orphan: OrphanCollectionInfo, documents: list[VectorDocument], tally: _Tally) -> None:
        """Move one page; counts are applied only once the whole page settled.

        A memory leaves the orphan only after the current collection is read back to
        hold it, so a failed embed, write or removal keeps it where it was (counted as
        failed). Memories without text can be neither embedded nor recalled and leave
        with the page. The model call runs outside the family lock, which is taken again
        to settle the page against what the orphan and the current collection hold by then.
        """
        try:
            embedded = await self._embed_unmigrated(orphan, documents)
            async with family_lock(self._vector, self._config):
                await self._settle_page(orphan, documents, embedded, tally)
        except Exception as e:
            logger.warning("Reindex failed for %d %s memories: %s", len(documents), orphan.memory_type, e)
            tally.failed += len(documents)

    async def _embed_unmigrated(self, orphan: OrphanCollectionInfo, documents: list[VectorDocument]) -> _Embedded:
        """Embed what the current collection does not hold yet (memories written since the switch win)."""
        target = current_collection(self._config, MemoryType(orphan.memory_type))
        candidates = [d for d in documents if d.content.strip()]
        missing = await self._missing_from(target, candidates) if candidates else []
        return await self._embed(orphan.memory_type, missing)

    async def _settle_page(
        self,
        orphan: OrphanCollectionInfo,
        documents: list[VectorDocument],
        embedded: _Embedded,
        tally: _Tally,
    ) -> None:
        """Write what the page still has to move, read it back, then remove it from the orphan (family lock held).

        The orphan and the current collection are read again because both can have changed
        while the page was embedded: a memory deleted meanwhile is dropped, one that reached the
        current collection is left as it is, and one that left it has no new vector yet, so it
        stays in the orphan (counted as failed) and moves on the next run.
        """
        vector, _ = self._vec()  # type: ignore[attr-defined]
        if not await vector.collection_exists(orphan.collection_name):
            return  # a bulk deletion removed the collection while the page was embedded
        remaining = {d.id for d in await vector.get(orphan.collection_name, [d.id for d in documents]) or []}
        live = [d for d in documents if d.id in remaining]
        if not live:
            return
        target = current_collection(self._config, MemoryType(orphan.memory_type))
        candidates = [d for d in live if d.content.strip()]
        missing = await self._missing_from(target, candidates) if candidates else []
        ready = [d for d in missing if d.id in embedded]
        unconfirmed = {d.id for d in missing if d.id not in embedded}
        if ready:
            await self._write_embedded(orphan.memory_type, target, embedded, [d.id for d in ready])
            unconfirmed |= {d.id for d in await self._missing_from(target, ready)}
        settled = [d.id for d in live if d.id not in unconfirmed]
        if settled:
            await vector.delete_by_filter(orphan.collection_name, {"id": {"$in": settled}})
        tally.failed += len(unconfirmed)
        tally.migrated += len(missing) - len(unconfirmed)
        tally.skipped += len(live) - len(missing)

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

    async def _embed(self, memory_type: str, documents: list[VectorDocument]) -> _Embedded:
        """Embed ``documents`` with the current model; vectors are never carried over, they belong to the old one.

        Semantic and episodic memories are copied verbatim (payload carries every persisted
        field) so nothing depends on model round-tripping; conversations keep their raw /
        summary layout through the conversation embedder.
        """
        if not documents:
            return _Embedded()
        _, embedding = self._vec()  # type: ignore[attr-defined]
        if memory_type == "conversation":
            conversations = [doc_to_conversation(d, include_raw=True, config=self._config) for d in documents]
            for conversation in conversations:
                conversation.raw_embedding = None
                conversation.summary_embedding = None
            await embed_conversations(conversations, embedding, self._cache)
            return _Embedded(conversations={c.id: c for c in conversations})
        vectors = await embed_batch([d.content for d in documents], embedding, self._cache)
        return _Embedded(
            documents={
                d.id: d.model_copy(update={"vector": fresh}) for d, fresh in zip(documents, vectors, strict=True)
            }
        )

    async def _write_embedded(self, memory_type: str, target: str, embedded: _Embedded, ids: list[str]) -> None:
        """Write the embedded memories ``ids`` into the current model's collection (no model call)."""
        vector, embedding = self._vec()  # type: ignore[attr-defined]
        if memory_type == "conversation":
            conversations = [embedded.conversations[memory_id] for memory_id in ids]
            await store_conversations_batch(conversations, vector, self._config, embedding, self._cache)
            return
        await vector.upsert(target, [embedded.documents[memory_id] for memory_id in ids])
