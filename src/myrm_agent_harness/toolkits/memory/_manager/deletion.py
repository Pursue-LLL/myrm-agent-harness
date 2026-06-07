"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory._manager.helpers import _memory_ref
from myrm_agent_harness.toolkits.memory._manager.shared import (
    EpisodicMemory,
    MemoryError,
    MemoryMutationRef,
    MemoryMutationResult,
    MemoryNotFoundError,
    MemoryType,
    SemanticMemory,
    Sequence,
    VectorDocument,
    delete_from_vector,
    doc_to_episodic,
    doc_to_semantic,
    logger,
)


class MemoryManagerDeletionMixin:
    # ── Delete ──

    async def delete_memory(self, collection: str, ids: list[str], *, allow_pinned: bool = True) -> int:
        if self._vector is None:
            raise MemoryError("Vector backend is required but not provided")
        if ids:
            docs = await self._vector.get(collection, ids) or []
            owned_ids = [
                doc.id
                for doc in docs
                if self._owns_vector_doc(doc) and (allow_pinned or not doc.metadata.get("pinned"))
            ]
            if not owned_ids:
                return 0
            ids = owned_ids
        deleted = await delete_from_vector(collection, ids, self._vector)
        if self._graph is not None:
            for memory_id in ids:
                try:
                    await self._graph.delete_subgraph(memory_id)
                except Exception as e:
                    logger.warning("Graph cleanup failed for %s: %s", memory_id, e)
        return deleted

    async def delete_rule(self, rule_id: str, *, allow_pinned: bool = True) -> bool:
        if not allow_pinned:
            rule = await self._rel().get_rule(rule_id, namespaces=self._namespaces)
            if rule is not None and rule.pinned:
                return False
        return await self._rel().delete_rule(rule_id)

    async def delete_memories_by_metadata(
        self,
        metadata_key: str,
        metadata_value: str,
        *,
        memory_types: Sequence[MemoryType] | None = None,
    ) -> dict[str, int]:
        """Delete owned memories whose flat metadata contains an exact key/value pair."""

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
                memory_ids = [doc_id for doc_id, owned in await self._collect_vector_ids(collection, filters) if owned]
                deleted = await self.delete_memory(collection, memory_ids)
                counts[memory_type.value] = deleted

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
                if await self._relational.delete_rule(rule_id):
                    deleted_rules += 1
            counts[MemoryType.PROCEDURAL.value] = deleted_rules

        return counts

    async def delete_memories_by_ids(self, memory_ids_by_type: dict[str, list[str]]) -> MemoryMutationResult:
        """Delete owned memories by explicit type/id refs and return exact outcomes."""

        result = MemoryMutationResult()
        vector_collections: dict[str, str] = {
            MemoryType.SEMANTIC.value: self._config.semantic_collection,
            MemoryType.EPISODIC.value: self._config.episodic_collection,
            MemoryType.CONVERSATION.value: self._config.conversation_collection,
        }
        for memory_type, memory_ids in memory_ids_by_type.items():
            ids = [memory_id for memory_id in memory_ids if memory_id]
            if not ids:
                continue
            collection = vector_collections.get(memory_type)
            if collection is not None:
                await self._delete_vector_memories_by_ids(
                    result,
                    memory_type=memory_type,
                    collection=collection,
                    ids=ids,
                )
                continue
            if memory_type == MemoryType.PROCEDURAL.value and self._relational is not None:
                for rule_id in ids:
                    rule = await self._relational.get_rule(rule_id, namespaces=self._namespaces)
                    if rule is None:
                        result.missing_refs.append(
                            MemoryMutationRef(
                                memory_type=memory_type,
                                memory_id=rule_id,
                                backend="relational",
                                reason="not_found",
                            )
                        )
                        continue
                    if await self._relational.delete_rule(rule_id):
                        result.deleted_refs.append(
                            MemoryMutationRef(memory_type=memory_type, memory_id=rule_id, backend="relational")
                        )
                    else:
                        result.failed_refs.append(
                            MemoryMutationRef(
                                memory_type=memory_type,
                                memory_id=rule_id,
                                backend="relational",
                                reason="delete_failed",
                            )
                        )
                continue
            for memory_id in ids:
                result.failed_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend="unavailable",
                        reason="backend_unavailable",
                    )
                )
        return result

    async def _delete_vector_memories_by_ids(
        self,
        result: MemoryMutationResult,
        *,
        memory_type: str,
        collection: str,
        ids: list[str],
    ) -> None:
        if self._vector is None:
            for memory_id in ids:
                result.failed_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason="backend_unavailable",
                    )
                )
            return
        try:
            docs = await self._vector.get(collection, ids) or []
        except Exception as e:
            for memory_id in ids:
                result.failed_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason=f"read_failed:{type(e).__name__}",
                    )
                )
            return

        docs_by_id = {doc.id: doc for doc in docs}
        for memory_id in ids:
            doc = docs_by_id.get(memory_id)
            if doc is None:
                result.missing_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason="not_found",
                    )
                )
            elif not self._owns_vector_doc(doc):
                result.forbidden_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason="scope_mismatch",
                    )
                )

        owned_ids = [memory_id for memory_id, doc in docs_by_id.items() if self._owns_vector_doc(doc)]
        if not owned_ids:
            return
        try:
            deleted_count = await delete_from_vector(collection, owned_ids, self._vector)
        except Exception as e:
            for memory_id in owned_ids:
                result.failed_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason=f"delete_failed:{type(e).__name__}",
                    )
                )
            return

        if deleted_count == len(owned_ids):
            deleted_ids = owned_ids
        else:
            remaining_docs = await self._vector.get(collection, owned_ids) or []
            remaining_ids = {doc.id for doc in remaining_docs}
            deleted_ids = [memory_id for memory_id in owned_ids if memory_id not in remaining_ids]
            for memory_id in remaining_ids:
                result.failed_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason="delete_incomplete",
                    )
                )

        for memory_id in deleted_ids:
            result.deleted_refs.append(
                MemoryMutationRef(memory_type=memory_type, memory_id=memory_id, backend=collection)
            )
            if self._graph is not None:
                try:
                    await self._graph.delete_subgraph(memory_id)
                except Exception as e:
                    logger.warning("Graph cleanup failed for %s: %s", memory_id, e)

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

    async def delete_all(self) -> dict[str, int]:
        uid, counts = self._user_id, {}
        if self._relational:
            try:
                counts["relational"] = await self._relational.delete_all()
            except Exception as e:
                logger.warning("Error deleting relational: %s", e)
        if self._vector:
            for coll in (
                self._config.semantic_collection,
                self._config.episodic_collection,
            ):
                try:
                    counts[coll] = await self._vector.delete_by_filter(coll, {})
                except Exception as e:
                    logger.warning("Error deleting %s: %s", coll, e)
        if self._graph is not None:
            try:
                counts["graph"] = await self._graph.delete_all_by_owner(uid)
            except Exception as e:
                logger.warning("Error deleting graph data: %s", e)
        return counts

    async def _collect_vector_ids(self, collection: str, filters: dict[str, str]) -> list[tuple[str, bool]]:
        if self._vector is None:
            return []
        ids: list[tuple[str, bool]] = []
        offset: str | None = None
        while True:
            docs, offset = await self._vector.scroll(collection, limit=500, offset=offset, filters=filters)
            ids.extend((doc.id, self._owns_vector_doc(doc)) for doc in docs)
            if offset is None:
                return ids

    async def _collect_vector_docs(self, collection: str, filters: dict[str, str]) -> list[VectorDocument]:
        if self._vector is None:
            return []
        collected: list[VectorDocument] = []
        offset: str | None = None
        while True:
            docs, offset = await self._vector.scroll(collection, limit=500, offset=offset, filters=filters)
            collected.extend(docs)
            if offset is None:
                return collected

    def _owns_vector_doc(self, doc: VectorDocument) -> bool:
        stored_uid = doc.metadata.get("user_id")
        if stored_uid and stored_uid != self._user_id:
            return False
        raw_namespaces = doc.metadata.get("namespaces")
        if isinstance(raw_namespaces, list) and raw_namespaces:
            namespaces = {value for value in raw_namespaces if isinstance(value, str)}
            return bool(namespaces.intersection(self._namespaces))
        primary_namespace = doc.metadata.get("primary_namespace")
        return not primary_namespace or primary_namespace in self._namespaces

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
            if doc.metadata.get("user_id") != self._user_id:
                raise MemoryNotFoundError(f"Memory {memory_id} not found")
            is_archived = doc.metadata.get("status") == "archived" or doc.metadata.get("archived")
            if not is_archived:
                raise MemoryError(f"Memory {memory_id} is not archived")
            doc.metadata["status"] = "active"
            doc.metadata.pop("archived", None)
            doc.metadata.pop("archived_at", None)
            doc.metadata.pop("archive_reason", None)
            await self._vector.upsert(coll, [doc])
            return converter(doc)

        raise MemoryNotFoundError(f"Memory {memory_id} not found")

    async def close(self) -> None:
        if self._relational and hasattr(self._relational, "close"):
            await self._relational.close()
        if self._vector:
            await self._vector.close()
        if self._graph:
            await self._graph.close()
        if self._preference_strategy is not None:
            await self._preference_strategy.close()
