"""MemoryManager archival TTL retention mixin module.

[INPUT]
- memory._manager.shared::ARCHIVE_RETENTION_DAYS (POS: archive retention window)
- memory._manager.shared::logger (POS: module logger)

[OUTPUT]
- MemoryManagerArchivalMixin: TTL retention purge for expired archived memories and rules

[POS]
Memory lifecycle archiver — reclaims archived memories and rules past their retention window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from myrm_agent_harness.toolkits.memory._manager.shared import (
    ARCHIVE_RETENTION_DAYS,
    logger,
)


class MemoryManagerArchivalMixin:
    """Provides expired archive purge capabilities for MemoryManager."""

    # Dynamic mixin attributes satisfied by MemoryManagerCore / DeletionMixin
    _vector: Any
    _config: Any
    _rel: Any
    _namespaces: Any
    delete_memory: Any
    delete_rule: Any

    async def purge_expired_archived_memories(self, *, ttl_days: int = ARCHIVE_RETENTION_DAYS) -> int:
        """Permanently purge soft-deleted memories whose archive retention has expired.

        Scans semantic and episodic collections for documents marked with
        ``status="archived"`` or ``archived=True``, checks their
        ``archive_expires_at`` (or ``archived_at`` + ttl_days), and physically
        deletes expired ones with full graph cascade.

        The ``archived_at`` fallback reclaims entries archived before the
        expiration stamp was written by every archival path.
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

    async def purge_expired_archived_rules(self, *, ttl_days: int = ARCHIVE_RETENTION_DAYS) -> int:
        """Permanently delete procedural rules whose archive retention has expired.

        Archived rules carry ``archive_expires_at`` in metadata. Rules archived
        before every archival path stamped an expiration fall back to
        ``archived_at`` + ``ttl_days`` so they are still reclaimed.

        ``allow_protected=False`` keeps user-endorsed rules permanently
        recoverable: they are skipped instead of hard-deleted.
        """
        try:
            rules = await self._rel().list_rules(
                active_only=False,
                limit=1000,
                namespaces=self._namespaces,
            )
        except Exception as exc:
            logger.warning("purge_expired_archived_rules: failed to list rules: %s", exc)
            return 0

        now_iso = datetime.now(UTC).isoformat()
        now_dt = datetime.now(UTC)
        purged_total = 0

        for rule in rules:
            if rule.is_active:
                continue
            metadata = rule.metadata or {}
            expires_at = metadata.get("archive_expires_at")
            archived_at = metadata.get("archived_at")

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

            if is_expired and await self.delete_rule(rule.id, allow_protected=False):
                purged_total += 1

        if purged_total > 0:
            logger.info("purge_expired_archived_rules: permanently purged %d expired rules", purged_total)

        return purged_total


__all__ = ["MemoryManagerArchivalMixin"]
