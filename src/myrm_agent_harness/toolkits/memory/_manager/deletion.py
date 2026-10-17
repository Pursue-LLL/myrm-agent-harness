"""MemoryManager deletion and cascade eviction mixin module.

[INPUT]
- memory._manager.archival::MemoryManagerArchivalMixin (POS: memory lifecycle archiver)
- memory._manager.queries::MemoryManagerQueriesMixin (POS: metadata and session query mixin)
- memory._manager.model_collections::{current_collection, drop_from_previous_models, family_lock} (POS: per-model collections and the lock shared with the migration)
- memory._internal.graph_cascade::cascade_clean_derived_graph_nodes (POS: cascade clean claim graph)

[OUTPUT]
- MemoryManagerDeletionMixin: ownership-gated delete by id with cascade clean, and the vector-id / ownership helpers the bulk deletions share

[POS]
Memory deletion mixin — owns vector/relational deletion, graph cascade, and embedding cache eviction.
Deleting a memory removes every copy of it: the one the current model reads and the one an interrupted
migration left in a previous model's collection (``delete_memories_by_ids`` is the exact-ref undo and
touches the current collection only). Deleting a whole set at once lives in ``bulk_deletion``.
"""

from __future__ import annotations

from typing import Any

from myrm_agent_harness.toolkits.memory._internal.graph_cascade import (
    cascade_clean_derived_graph_nodes,
)
from myrm_agent_harness.toolkits.memory._manager.archival import (
    MemoryManagerArchivalMixin,
)
from myrm_agent_harness.toolkits.memory._manager.model_collections import (
    current_collection,
    drop_from_previous_models,
    family_lock,
)
from myrm_agent_harness.toolkits.memory._manager.queries import (
    MemoryManagerQueriesMixin,
)
from myrm_agent_harness.toolkits.memory._manager.shared import (
    FilterDict,
    MemoryError,
    MemoryMutationRef,
    MemoryMutationResult,
    MemoryType,
    VectorDocument,
    delete_from_vector,
    logger,
)


class MemoryManagerDeletionMixin(MemoryManagerArchivalMixin, MemoryManagerQueriesMixin):
    """Provides pure deletion and cascade eviction operations for MemoryManager."""

    # Dynamic mixin attributes satisfied by MemoryManagerCore / StorageMixin
    _graph: Any
    _vector: Any
    _relational: Any
    _cache: Any
    _config: Any
    _namespaces: Any
    _user_id: Any
    _active_session: Any
    _preference_strategy: Any
    _rel: Any

    # ── Graph cascade ──

    async def _cascade_clean_derived_graph_nodes(self, memory_id: str) -> None:
        """Remove Claim Graph nodes derived from a deleted/archived memory."""
        await cascade_clean_derived_graph_nodes(self._graph, memory_id)

    # ── Delete ──

    async def delete_memory(self, collection: str, ids: list[str], *, allow_protected: bool = True) -> int:
        """Delete the owned memories among ``ids`` from ``collection`` and from the previous models' collections.

        A model switch can leave a memory in a previous model's collection as well (an interrupted
        migration removes it there only after the current collection holds it), and the next
        migration would bring a deleted memory back. Those copies go first: if one cannot be
        removed this raises with the memory still in ``collection``, so it stays listed and the
        deletion can be repeated.
        """
        if self._vector is None:
            raise MemoryError("Vector backend is required but not provided")
        async with family_lock(self._vector, self._config):
            docs = await self._owned_docs(collection, ids, allow_protected)
            if not docs:
                return 0
            failed = await drop_from_previous_models(self._vector, self._config, collection, [d.id for d in docs])
            if failed:
                raise MemoryError(
                    f"Memories left in previous embedding models' collections: {', '.join(failed)}; "
                    f"nothing was deleted from {collection}"
                )
            deleted = await delete_from_vector(collection, [doc.id for doc in docs], self._vector)
        # Cleaning what was derived from them needs no lock: they are already gone from every collection.
        await self._forget_derived(docs)
        return deleted

    async def delete_memory_by_id(self, memory_id: str) -> int:
        """Delete a single owned memory, resolving its collection from the id.

        ``delete_memory`` requires the caller to know the vector collection up
        front. Governance and approval flows only hold a memory id, so this
        probes the current model's vector collections and delegates to the
        canonical delete path (ownership-gated, every model's copy, with graph/cache cascade).
        """
        if self._vector is None:
            return 0
        for memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.CONVERSATION):
            collection = current_collection(self._config, memory_type)
            if await self._vector.get(collection, [memory_id]):
                return await self.delete_memory(collection, [memory_id])
        return 0

    async def _delete_owned(self, collection: str, ids: list[str]) -> int:
        """Delete the owned memories among ``ids`` from ``collection`` only (the caller covers the other collections)."""
        docs = await self._owned_docs(collection, ids, True)
        if not docs:
            return 0
        deleted = await delete_from_vector(collection, [doc.id for doc in docs], self._vector)
        await self._forget_derived(docs)
        return deleted

    async def _owned_docs(self, collection: str, ids: list[str], allow_protected: bool) -> list[VectorDocument]:
        """The documents among ``ids`` this manager may delete: owned, and unpinned unless protected ones are allowed."""
        if not ids:
            return []
        docs = await self._vector.get(collection, ids) or []
        return [
            doc for doc in docs if self._owns_vector_doc(doc) and (allow_protected or not doc.metadata.get("pinned"))
        ]

    async def _forget_derived(self, docs: list[VectorDocument]) -> None:
        """Clean the claim graph, exact facts and embedding cache of memories whose documents were deleted."""
        for doc in docs:
            await self._cascade_clean_derived_graph_nodes(doc.id)
            if self._relational is not None and hasattr(self._relational, "delete_exact_fact"):
                try:
                    await self._relational.delete_exact_fact(doc.id)
                except Exception as e:
                    logger.debug("Failed to delete exact fact for %s: %s", doc.id, e)
        texts = [doc.content for doc in docs if doc.content]
        if self._cache is not None and texts:
            if hasattr(self._cache, "evict_batch"):
                await self._cache.evict_batch(texts)
            elif hasattr(self._cache, "evict"):
                for text in texts:
                    await self._cache.evict(text)

    async def delete_rule(self, rule_id: str, *, allow_protected: bool = True) -> bool:
        """Delete an owned procedural rule.

        Ownership is enforced via the manager's namespaces so a rule can only
        be deleted when it lives in the current scope — mirroring the
        ownership gate already applied to vector memories.

        ``allow_protected=False`` (automated and agent-facing paths) refuses to
        delete a user-endorsed rule, so the lock shared with
        distillation/merge/forgetting cannot be silently bypassed.
        """
        rule = await self._rel().get_rule(rule_id, namespaces=self._namespaces)
        if rule is None:
            return False
        if not allow_protected and rule.is_user_protected:
            return False
        deleted: bool = await self._rel().delete_rule(rule_id)
        if deleted:
            await self._cascade_clean_derived_graph_nodes(rule_id)
            evict_text = (
                getattr(rule, "action", None) or getattr(rule, "action_text", None) or getattr(rule, "content", None)
            )
            if self._cache is not None and evict_text and hasattr(self._cache, "evict"):
                await self._cache.evict(evict_text)
        return deleted

    async def delete_memories_by_ids(self, memory_ids_by_type: dict[str, list[str]]) -> MemoryMutationResult:
        """Delete owned memories by explicit type/id refs from the current model's collections, with exact outcomes.

        This is the undo of a write (import / restore rollback): it removes precisely what that
        write added and never reaches into the previous models' collections. Deleting a memory on
        the user's behalf goes through ``delete_memory``.
        """

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
                    if await self.delete_rule(rule_id):
                        result.deleted_refs.append(
                            MemoryMutationRef(
                                memory_type=memory_type,
                                memory_id=rule_id,
                                backend="relational",
                            )
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

        result.deleted_refs.extend(
            MemoryMutationRef(memory_type=memory_type, memory_id=memory_id, backend=collection)
            for memory_id in deleted_ids
        )
        await self._forget_derived([docs_by_id[memory_id] for memory_id in deleted_ids])

    async def _collect_vector_ids(self, collection: str, filters: FilterDict) -> list[tuple[str, bool]]:
        if self._vector is None:
            return []
        ids: list[tuple[str, bool]] = []
        offset: str | None = None
        while True:
            docs, offset = await self._vector.scroll(collection, limit=500, offset=offset, filters=filters)
            ids.extend((doc.id, self._owns_vector_doc(doc)) for doc in docs)
            if offset is None:
                return ids

    async def _collect_vector_docs(self, collection: str, filters: FilterDict) -> list[VectorDocument]:
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
        primary_namespace = doc.metadata.get("primary_namespace")
        if primary_namespace:
            return primary_namespace in self._namespaces
        raw_namespaces = doc.metadata.get("namespaces")
        if isinstance(raw_namespaces, list) and raw_namespaces:
            namespaces = {value for value in raw_namespaces if isinstance(value, str)}
            return bool(namespaces.intersection(self._namespaces))
        return True

    async def close(self) -> None:
        if self._active_session is not None:
            try:
                await self._active_session.flush()
            except Exception as e:
                logger.warning("Shutdown session flush failed (non-fatal): %s", e)
            self._active_session = None

        if self._relational and hasattr(self._relational, "close"):
            await self._relational.close()
        if self._vector:
            await self._vector.close()
        if self._graph:
            await self._graph.close()
        if self._preference_strategy is not None:
            await self._preference_strategy.close()


__all__ = ["MemoryManagerDeletionMixin"]
