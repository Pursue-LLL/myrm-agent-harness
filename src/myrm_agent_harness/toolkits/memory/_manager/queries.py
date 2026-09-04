"""MemoryManager metadata query and session count mixin module.

[INPUT]
- memory._manager.helpers::_memory_ref (POS: memory reference serializer)
- memory._manager.shared::MemoryType (POS: memory taxonomy enum)
- memory._manager.shared::Sequence (POS: collection sequence protocol)

[OUTPUT]
- MemoryManagerQueriesMixin: metadata-scoped id/ref query and chat session purge helpers

[POS]
Metadata and session query mixin — extracts memory ids/refs by metadata and aggregates chat stats.
"""

from __future__ import annotations

from typing import Any

from myrm_agent_harness.toolkits.memory._manager.helpers import _memory_ref
from myrm_agent_harness.toolkits.memory._manager.shared import (
    MemoryType,
    Sequence,
    logger,
)


class MemoryManagerQueriesMixin:
    """Provides metadata queries and chat session aggregation for MemoryManager."""

    # Dynamic mixin attributes satisfied by MemoryManagerCore / DeletionMixin
    _config: Any
    _vector: Any
    _relational: Any
    _namespaces: Any
    _collect_vector_ids: Any
    _collect_vector_docs: Any
    _owns_vector_doc: Any
    delete_memories_by_metadata: Any

    async def list_memory_ids_by_metadata(
        self,
        metadata_key: str,
        metadata_value: str,
        *,
        memory_types: Sequence[MemoryType] | None = None,
    ) -> dict[str, list[str]]:
        """List owned memory ids whose flat metadata contains an exact key/value pair."""

        selected_types = tuple(
            memory_types
            or (
                MemoryType.SEMANTIC,
                MemoryType.EPISODIC,
                MemoryType.CONVERSATION,
                MemoryType.PROCEDURAL,
            )
        )
        matches: dict[str, list[str]] = {}
        vector_collections: dict[MemoryType, str] = {
            MemoryType.SEMANTIC: self._config.semantic_collection,
            MemoryType.EPISODIC: self._config.episodic_collection,
            MemoryType.CONVERSATION: self._config.conversation_collection,
        }

        if self._vector is not None:
            filters = {metadata_key: metadata_value}
            for memory_type, collection in vector_collections.items():
                if memory_type not in selected_types:
                    continue
                matches[memory_type.value] = [
                    doc_id for doc_id, owned in await self._collect_vector_ids(collection, filters) if owned
                ]

        if MemoryType.PROCEDURAL in selected_types and self._relational is not None:
            rule_ids: list[str] = []
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
                rule_ids.extend(rule.id for rule in rules if rule.metadata.get(metadata_key) == metadata_value)
                offset += len(rules)
            matches[MemoryType.PROCEDURAL.value] = rule_ids

        return matches

    async def list_memory_refs_by_metadata(
        self,
        metadata_key: str,
        metadata_value: str,
        *,
        memory_types: Sequence[MemoryType] | None = None,
    ) -> dict[str, list[dict[str, str]]]:
        """List owned memory refs and flat metadata markers for an exact metadata key/value pair."""

        selected_types = tuple(
            memory_types
            or (
                MemoryType.SEMANTIC,
                MemoryType.EPISODIC,
                MemoryType.CONVERSATION,
                MemoryType.PROCEDURAL,
            )
        )
        refs: dict[str, list[dict[str, str]]] = {}
        vector_collections: dict[MemoryType, str] = {
            MemoryType.SEMANTIC: self._config.semantic_collection,
            MemoryType.EPISODIC: self._config.episodic_collection,
            MemoryType.CONVERSATION: self._config.conversation_collection,
        }

        if self._vector is not None:
            filters = {metadata_key: metadata_value}
            for memory_type, collection in vector_collections.items():
                if memory_type not in selected_types:
                    continue
                refs[memory_type.value] = [
                    _memory_ref(doc.id, doc.metadata)
                    for doc in await self._collect_vector_docs(collection, filters)
                    if self._owns_vector_doc(doc)
                ]

        if MemoryType.PROCEDURAL in selected_types and self._relational is not None:
            rule_refs: list[dict[str, str]] = []
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
                rule_refs.extend(
                    _memory_ref(rule.id, rule.metadata)
                    for rule in rules
                    if rule.metadata.get(metadata_key) == metadata_value
                )
                offset += len(rules)
            refs[MemoryType.PROCEDURAL.value] = rule_refs

        return refs

    async def purge_by_source_chat_id(self, chat_id: str) -> dict[str, int]:
        """Cascade-delete all memories derived from a specific chat session.

        Deletes Semantic, Episodic, Conversation, and Procedural memories with
        matching source_chat_id metadata, plus any PendingRecords linked to this chat.
        Gracefully handles missing vector collections (returns 0 for those types).
        """
        try:
            counts = await self.delete_memories_by_metadata("source_chat_id", chat_id)
        except Exception as e:
            logger.warning("Vector cascade deletion skipped (chat=%s): %s", chat_id, e)
            counts = {}
        if self._relational is not None:
            pending_deleted = await self._relational.delete_pending_by_source_chat_id(chat_id)
            if pending_deleted:
                counts["pending"] = pending_deleted
        return counts

    async def count_by_source_chat_id(self, chat_id: str) -> dict[str, int]:
        """Count memories linked to a chat session (for UI preview before deletion)."""
        try:
            id_map = await self.list_memory_ids_by_metadata("source_chat_id", chat_id)
            result = {k: len(v) for k, v in id_map.items() if v}
        except Exception as e:
            logger.warning("Vector cascade count skipped (chat=%s): %s", chat_id, e)
            result = {}
        if self._relational is not None:
            pending_count = await self._relational.count_pending_by_source_chat_id(chat_id)
            if pending_count:
                result["pending"] = pending_count
        return result


__all__ = ["MemoryManagerQueriesMixin"]
