"""MemoryManager reindex mixin — detects orphan collections from model switch and re-embeds.

[INPUT]
- memory.config::MemoryConfig (POS: memory configuration with collection naming)
- vector.base::VectorStore (POS: abstract vector store with list_collections/get_collection_info)

[OUTPUT]
- MemoryManagerReindexMixin: detect_orphan_collections, reindex_from_orphans

[POS]
Handles embedding model hot-swap: detects collections belonging to previous models,
and re-embeds their content into the current model's collections via existing
export_all → import_memories pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.vector.base import CollectionInfo, VectorStore

logger = logging.getLogger(__name__)

_COLLECTION_PREFIXES = ("_semantic_", "_episodic_", "_conversation_")


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
    """Result of a reindex operation."""

    migrated: int
    skipped: int
    failed: int


ProgressCallback = Callable[[int, int, str], None]


def _extract_model_suffix(collection_name: str, prefix: str) -> str | None:
    """Extract the model suffix from a collection name after a known prefix infix."""
    idx = collection_name.find(prefix)
    if idx == -1:
        return None
    return collection_name[idx + len(prefix):]


class MemoryManagerReindexMixin:
    """Mixin providing orphan collection detection and reindex capabilities."""

    _config: MemoryConfig
    _vector: VectorStore | None

    async def detect_orphan_collections(self) -> list[OrphanCollectionInfo]:
        """Detect Qdrant collections from previous embedding models.

        Compares all collections matching our prefix against the current model's
        expected collection names. Collections that match the prefix pattern but
        use a different model suffix are considered orphans.
        """
        if self._vector is None:
            return []

        config = self._config
        current_collections = {
            config.semantic_collection,
            config.episodic_collection,
            config.conversation_collection,
        }
        prefix = config.collection_prefix

        try:
            all_collections = await self._vector.list_collections()
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
                info = await self._vector.get_collection_info(name)
                count = info.count if info else 0
            except Exception:
                count = 0

            if count == 0:
                continue

            orphans.append(OrphanCollectionInfo(
                collection_name=name,
                memory_type=memory_type,
                old_model_suffix=model_suffix,
                document_count=count,
            ))

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

        Uses the existing export_all → import_memories pipeline:
        1. For each orphan collection, scroll all documents (text only)
        2. Feed through import_memories which re-computes embeddings via store_batch
        3. Old collections are preserved (not deleted) as a safety net

        Args:
            progress_cb: Optional callback(current, total, phase) for progress reporting.
        """
        orphans = await self.detect_orphan_collections()
        if not orphans:
            return ReindexResult(migrated=0, skipped=0, failed=0)

        total = sum(o.document_count for o in orphans)
        migrated = 0
        skipped = 0
        failed = 0

        if progress_cb:
            progress_cb(0, total, "starting")

        for orphan in orphans:
            try:
                documents = await self._scroll_orphan_documents(orphan)
                import_data = self._documents_to_import_format(documents, orphan.memory_type)
                if import_data:
                    counts = await self.import_memories(import_data, skip_duplicates=True)  # type: ignore[attr-defined]
                    batch_migrated = sum(counts.values())
                    migrated += batch_migrated
                    skipped += orphan.document_count - batch_migrated
                else:
                    skipped += orphan.document_count

                if progress_cb:
                    progress_cb(migrated + skipped + failed, total, "migrating")

            except Exception as e:
                logger.warning(
                    "Reindex failed for orphan %s: %s", orphan.collection_name, e
                )
                failed += orphan.document_count

        if progress_cb:
            progress_cb(total, total, "completed")

        logger.info(
            "Reindex completed: migrated=%d, skipped=%d, failed=%d",
            migrated, skipped, failed,
        )
        return ReindexResult(migrated=migrated, skipped=skipped, failed=failed)

    async def _scroll_orphan_documents(self, orphan: OrphanCollectionInfo) -> list[dict[str, object]]:
        """Scroll all documents from an orphan collection as raw dicts."""
        if self._vector is None:
            return []

        batch_size = 100
        all_docs: list[dict[str, object]] = []
        cursor: str | None = None

        try:
            while True:
                docs, cursor = await self._vector.scroll(
                    collection=orphan.collection_name,
                    limit=batch_size,
                    offset=cursor,
                )
                for doc in docs:
                    payload: dict[str, object] = {**doc.metadata} if doc.metadata else {}
                    if doc.content:
                        payload.setdefault("content", doc.content)
                    all_docs.append(payload)
                if cursor is None:
                    break
        except Exception as e:
            logger.warning("Failed to scroll orphan %s: %s", orphan.collection_name, e)

        return all_docs

    @staticmethod
    def _documents_to_import_format(
        documents: list[dict[str, object]], memory_type: str,
    ) -> dict[str, list[dict[str, object]]]:
        """Convert scrolled documents into the format expected by import_memories."""
        if not documents:
            return {}

        type_key = memory_type
        cleaned: list[dict[str, object]] = []
        for doc in documents:
            entry = {k: v for k, v in doc.items() if k not in ("id", "embedding", "raw_embedding", "summary_embedding")}
            if "content" not in entry:
                continue
            cleaned.append(entry)

        return {type_key: cleaned} if cleaned else {}
