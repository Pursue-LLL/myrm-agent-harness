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
    ProceduralMemory,
    logger,
)

# Reclamation scans page through the archived set instead of trusting a single
# capped read, so entries beyond the first page are never stranded. Page and
# deletion ceilings bound one cycle's work: leftover entries are picked up by
# the next cycle, keeping maintenance latency predictable.
_PURGE_PAGE_SIZE = 500
_MAX_PURGE_PAGES_PER_COLLECTION = 40
_PURGE_DELETE_BATCH_SIZE = 500
_MAX_PURGE_DELETIONS_PER_CYCLE = 2000
_PURGE_RULE_PAGE_SIZE = 1000
_MAX_PURGE_RULE_PAGES = 10


def _retention_elapsed(metadata: dict[str, object], now: datetime, ttl_days: int) -> bool:
    """Whether an archived entry has outlived its retention window.

    ``archive_expires_at`` is authoritative when present. Entries archived
    before every write path stamped it fall back to ``archived_at`` + ttl_days
    so legacy archives are still reclaimed.
    """
    expires_at = metadata.get("archive_expires_at")
    if isinstance(expires_at, str):
        return expires_at <= now.isoformat()

    archived_at = metadata.get("archived_at")
    if not isinstance(archived_at, str):
        return False
    try:
        return now - datetime.fromisoformat(archived_at) >= timedelta(days=ttl_days)
    except ValueError:
        return False


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

        now = datetime.now(UTC)
        purged_total = 0
        # Archive status can be applied to semantic, episodic and conversation
        # memories, so every vector collection that can hold an archived entry
        # must be scanned or the entry would never be reclaimed.
        vector_collections = (
            self._config.semantic_collection,
            self._config.episodic_collection,
            self._config.conversation_collection,
        )

        for coll in vector_collections:
            cursor: str | None = None
            pages_scanned = 0
            expired_ids: list[str] = []
            while pages_scanned < _MAX_PURGE_PAGES_PER_COLLECTION:
                try:
                    docs, cursor = await self._vector.scroll(
                        coll,
                        filters={"archived": True},
                        limit=_PURGE_PAGE_SIZE,
                        offset=cursor,
                    )
                except Exception as exc:
                    logger.warning("purge_expired_archived_memories: failed to scroll %s: %s", coll, exc)
                    break
                pages_scanned += 1

                expired_ids.extend(doc.id for doc in docs if _retention_elapsed(doc.metadata, now, ttl_days))

                if cursor is None or not docs:
                    break
            else:
                logger.warning(
                    "purge_expired_archived_memories: %s hit the %d-page cap; "
                    "remaining expired entries are reclaimed on the next cycle",
                    coll,
                    _MAX_PURGE_PAGES_PER_COLLECTION,
                )

            # Delete only after the scan finishes: mutating the collection mid-scan
            # would invalidate the cursor we are paging with. Bounded per batch and
            # per cycle so one maintenance cycle cannot monopolize the event loop
            # with graph cascades; what is left waits for the next cycle.
            remaining_budget = _MAX_PURGE_DELETIONS_PER_CYCLE - purged_total
            if remaining_budget <= 0:
                logger.warning(
                    "purge_expired_archived_memories: reached the %d-deletion cycle budget; "
                    "remaining expired entries are reclaimed on the next cycle",
                    _MAX_PURGE_DELETIONS_PER_CYCLE,
                )
                break
            for start in range(0, min(len(expired_ids), remaining_budget), _PURGE_DELETE_BATCH_SIZE):
                batch = expired_ids[start : start + _PURGE_DELETE_BATCH_SIZE]
                purged_total += await self.delete_memory(coll, batch)

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
            rules: list[ProceduralMemory] = []
            offset = 0
            for _ in range(_MAX_PURGE_RULE_PAGES):
                page = await self._rel().list_rules(
                    active_only=False,
                    limit=_PURGE_RULE_PAGE_SIZE,
                    offset=offset,
                    namespaces=self._namespaces,
                )
                rules.extend(page)
                if len(page) < _PURGE_RULE_PAGE_SIZE:
                    break
                offset += len(page)
            else:
                logger.warning(
                    "purge_expired_archived_rules: hit the %d-page cap; "
                    "remaining expired rules are reclaimed on the next cycle",
                    _MAX_PURGE_RULE_PAGES,
                )
        except Exception as exc:
            logger.warning("purge_expired_archived_rules: failed to list rules: %s", exc)
            return 0

        now = datetime.now(UTC)
        purged_total = 0

        for rule in rules:
            if rule.is_active:
                continue
            if _retention_elapsed(rule.metadata or {}, now, ttl_days) and await self.delete_rule(
                rule.id, allow_protected=False
            ):
                purged_total += 1

        if purged_total > 0:
            logger.info("purge_expired_archived_rules: permanently purged %d expired rules", purged_total)

        return purged_total


__all__ = ["MemoryManagerArchivalMixin"]
