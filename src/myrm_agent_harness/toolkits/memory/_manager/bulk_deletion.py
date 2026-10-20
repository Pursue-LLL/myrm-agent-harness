"""MemoryManager bulk deletion mixin — erases a whole set of memories across every embedding model's collections.

[INPUT]
- memory._manager.deletion::MemoryManagerDeletionMixin (POS: single-memory deletion primitives and the ownership gate)
- memory._manager.model_collections::{current_collection, family_lock, memory_collections, retire_if_drained} (POS: every embedding model's collections and the lock shared with the migration)

[OUTPUT]
- MemoryManagerBulkDeletionMixin: delete_memories_by_metadata (chat-purge cascade), delete_all

[POS]
Bulk deletion — a metadata cascade or a full erase reaches the memories an embedding-model switch left in
previous models' collections, because those are the same memories. Both run under the collection family's
lock so a migration page in flight cannot write back what they removed. They visit every collection
themselves, so they call the unlocked, single-collection ``_delete_owned`` (``asyncio.Lock`` is not re-entrant).
"""

from __future__ import annotations

import asyncio

from myrm_agent_harness.toolkits.memory._manager.deletion import MemoryManagerDeletionMixin
from myrm_agent_harness.toolkits.memory._manager.model_collections import (
    current_collection,
    family_lock,
    memory_collections,
    retire_if_drained,
)
from myrm_agent_harness.toolkits.memory._manager.shared import (
    FilterDict,
    MemoryError,
    MemoryType,
    Sequence,
    logger,
)


class MemoryManagerBulkDeletionMixin(MemoryManagerDeletionMixin):
    """Provides metadata-cascade and erase-everything deletion for MemoryManager."""

    async def delete_memories_by_metadata(
        self,
        metadata_key: str,
        metadata_value: str,
        *,
        memory_types: Sequence[MemoryType] | None = None,
    ) -> dict[str, int]:
        """Delete owned memories whose flat metadata contains an exact key/value pair.

        User-initiated cascades (chat session purge) run with the user's
        consent, so protected entries are deleted together with the rest.
        """

        selected_types = tuple(
            memory_types
            or (
                MemoryType.SEMANTIC,
                MemoryType.EPISODIC,
                MemoryType.CONVERSATION,
                MemoryType.PROCEDURAL,
            )
        )
        counts: dict[str, int] = {}

        if self._vector is not None:
            filters: FilterDict = {metadata_key: metadata_value}
            # Memories a model switch left in a previous model's collections are the same memories.
            async with family_lock(self._vector, self._config):
                for memory_type, collections in (await memory_collections(self._vector, self._config)).items():
                    if memory_type not in selected_types:
                        continue
                    counts[memory_type.value] = 0
                    for collection in collections:
                        ids = [doc_id for doc_id, owned in await self._collect_vector_ids(collection, filters) if owned]
                        counts[memory_type.value] += await self._delete_owned(collection, ids)
                        if collection != current_collection(self._config, memory_type):
                            await retire_if_drained(self._vector, collection)

        if MemoryType.PROCEDURAL in selected_types and self._relational is not None:
            matching_rule_ids: list[str] = []
            offset = 0
            while True:
                rules = await self._relational.list_rules(
                    active_only=False,
                    limit=500,
                    offset=offset,
                    namespaces=self._namespaces,
                )
                if not rules:
                    break
                for rule in rules:
                    if rule.metadata.get(metadata_key) == metadata_value:
                        matching_rule_ids.append(rule.id)
                offset += len(rules)
            deleted_rules = 0
            for rule_id in matching_rule_ids:
                if await self.delete_rule(rule_id):
                    deleted_rules += 1
            counts[MemoryType.PROCEDURAL.value] = deleted_rules

        return counts

    async def delete_all(self) -> dict[str, int]:
        """Erase every memory, in every embedding model's collections.

        Each backend is attempted before reporting. A relational or vector failure raises
        afterwards, so a deletion that left memories behind never reports success; the
        derived graph and embedding cache are cleared best-effort.
        """
        uid = self._user_id
        counts: dict[str, int] = {}
        failed: list[str] = []
        if self._relational:
            try:
                counts["relational"] = await self._relational.delete_all()
            except Exception as e:
                logger.warning("Error deleting relational: %s", e)
                failed.append("relational")
        if self._vector:
            async with family_lock(self._vector, self._config):
                try:
                    collections_by_type = await memory_collections(self._vector, self._config)
                except MemoryError as e:
                    # A listing failure hides the previous models' collections: clearing only the
                    # current model would report success while those copies survive.
                    logger.warning("Cannot enumerate memory collections for delete_all: %s", e)
                    collections_by_type = {}
                    failed.append(f"{self._config.collection_prefix}* (collection listing failed)")
                for memory_type, collections in collections_by_type.items():
                    for coll in collections:
                        try:
                            counts[coll] = await self._vector.delete_by_filter(coll, {})
                            if coll != current_collection(self._config, memory_type):
                                await retire_if_drained(self._vector, coll)
                        except Exception as e:
                            logger.warning("Error deleting %s: %s", coll, e)
                            failed.append(coll)
        if self._graph is not None:
            try:
                counts["graph"] = await self._graph.delete_all_by_owner(uid)
            except Exception as e:
                logger.warning("Error deleting graph data: %s", e)
        if self._cache is not None and hasattr(self._cache, "clear"):
            try:
                if asyncio.iscoroutinefunction(self._cache.clear):
                    await self._cache.clear()
                else:
                    self._cache.clear()
            except Exception as e:
                logger.warning("Error clearing cache in delete_all: %s", e)
        if failed:
            raise MemoryError(f"delete_all left memories behind in: {', '.join(failed)}")
        return counts


__all__ = ["MemoryManagerBulkDeletionMixin"]
