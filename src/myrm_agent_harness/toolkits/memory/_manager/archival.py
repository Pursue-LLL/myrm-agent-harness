"""MemoryManager archival and TTL retention mixin module.

[INPUT]
- memory._manager.shared::MemoryError (POS: base memory error)
- memory._manager.shared::MemoryNotFoundError (POS: memory not found error)
- memory._manager.shared::SemanticMemory (POS: semantic memory model)
- memory._manager.shared::EpisodicMemory (POS: episodic memory model)

[OUTPUT]
- MemoryManagerArchivalMixin: unarchive and TTL retention purge operations

[POS]
Memory lifecycle archiver — handles memory restoration and TTL expiration purge.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from myrm_agent_harness.toolkits.memory._manager.shared import (
    EpisodicMemory,
    MemoryError,
    MemoryNotFoundError,
    SemanticMemory,
    doc_to_episodic,
    doc_to_semantic,
    logger,
)


class MemoryManagerArchivalMixin:
    """Provides unarchive and expired archive purge capabilities for MemoryManager."""

    # Dynamic mixin attributes satisfied by MemoryManagerCore / DeletionMixin
    _vector: Any
    _config: Any
    _owns_vector_doc: Any
    delete_memory: Any

    async def unarchive_memory(self, memory_id: str) -> SemanticMemory | EpisodicMemory:
        """Restore an archived memory to active status."""
        if self._vector is None:
            raise MemoryError("Vector backend is required but not provided")

        for coll, converter in (
            (self._config.semantic_collection, doc_to_semantic),
            (self._config.episodic_collection, doc_to_episodic),
        ):
            docs = await self._vector.get(coll, [memory_id])
            if not docs:
                continue
            doc = docs[0]
            if not self._owns_vector_doc(doc):
                raise MemoryNotFoundError(f"Memory {memory_id} not found")
            is_archived = doc.metadata.get("status") == "archived" or doc.metadata.get("archived")
            if not is_archived:
                raise MemoryError(f"Memory {memory_id} is not archived")
            doc.metadata["status"] = "active"
            doc.metadata["archived"] = False
            doc.metadata.pop("archived_at", None)
            doc.metadata.pop("archive_reason", None)
            await self._vector.upsert(coll, [doc])
            return converter(doc)

        raise MemoryNotFoundError(f"Memory {memory_id} not found")

    async def purge_expired_archived_memories(self, *, ttl_days: int = 7) -> int:
        """Permanently purge soft-deleted memories whose archive retention has expired.

        Scans semantic and episodic collections for documents marked with
        ``status="archived"`` or ``archived=True``, checks their
        ``archive_expires_at`` (or ``archived_at`` + ttl_days), and physically
        deletes expired ones with full graph cascade.
        """
        if self._vector is None:
            return 0

        now_iso = datetime.now(UTC).isoformat()
        now_dt = datetime.now(UTC)
        purged_total = 0
        vector_collections = (self._config.semantic_collection, self._config.episodic_collection)

        for coll in vector_collections:
            try:
                docs, _ = await self._vector.scroll(
                    coll,
                    filters={"archived": True},
                    limit=500,
                )
            except Exception as exc:
                logger.warning("purge_expired_archived_memories: failed to scroll %s: %s", coll, exc)
                continue

            expired_ids: list[str] = []
            for doc in docs:
                expires_at = doc.metadata.get("archive_expires_at")
                archived_at = doc.metadata.get("archived_at")

                is_expired = False
                if isinstance(expires_at, str) and expires_at <= now_iso:
                    is_expired = True
                elif not expires_at and isinstance(archived_at, str):
                    try:
                        arch_dt = datetime.fromisoformat(archived_at)
                        if now_dt - arch_dt >= timedelta(days=ttl_days):
                            is_expired = True
                    except ValueError:
                        pass

                if is_expired:
                    expired_ids.append(doc.id)

            if expired_ids:
                deleted = await self.delete_memory(coll, expired_ids)
                purged_total += deleted

        if purged_total > 0:
            logger.info("purge_expired_archived_memories: permanently purged %d expired memories", purged_total)

        return purged_total


__all__ = ["MemoryManagerArchivalMixin"]
