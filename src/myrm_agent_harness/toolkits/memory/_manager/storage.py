"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations

import asyncio

from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_index import (
    BM25SparseIndexStore,
)
from myrm_agent_harness.toolkits.memory._internal.storage_converters import (
    episodic_to_doc,
    semantic_to_doc,
)
from myrm_agent_harness.toolkits.memory._manager.shared import (
    AnyMemory,
    ConsolidationConfig,
    ConversationMemory,
    EmbeddingProtocol,
    EpisodicMemory,
    MemoryError,
    MemorySearchResult,
    ProceduralMemory,
    RelationalStoreProtocol,
    SemanticMemory,
    VectorStoreProtocol,
    apply_channel_affinity,
    bind_scope,
    logger,
    store_episodic,
    store_episodics_batch,
    store_semantic,
    store_semantics_batch,
)


class MemoryManagerStorageMixin:
    # ── Private: backend accessors (fail-fast if not configured) ──

    def _vec(self) -> tuple[VectorStoreProtocol, EmbeddingProtocol]:
        if self._vector is None or self._embedding is None:
            raise MemoryError("Vector + Embedding backends required")
        return self._vector, self._embedding

    def _rel(self) -> RelationalStoreProtocol:
        if self._relational is None:
            raise MemoryError("Relational backend required")
        return self._relational

    def _bind_scope[T: AnyMemory](self, memory: T) -> T:
        bound = bind_scope(memory, self._scope)
        if isinstance(bound, ProceduralMemory):
            if len(self._namespaces) > 1:
                bound.scope.primary_namespace = self._namespaces[1]
                bound.scope.namespaces = self._namespaces[:2]
                bound.scope.channel_id = None
                bound.scope.conversation_id = None
                bound.scope.task_id = None
            elif self._namespaces:
                bound.scope.primary_namespace = self._namespaces[0]
                bound.scope.namespaces = [self._namespaces[0]]
                bound.scope.agent_id = None
                bound.scope.channel_id = None
                bound.scope.conversation_id = None
                bound.scope.task_id = None
        return bound

    def _apply_channel_affinity(self, results: list[MemorySearchResult]) -> list[MemorySearchResult]:
        return apply_channel_affinity(results, current_channel_id=self._scope.channel_id)

    async def _store_semantic(self, memory: SemanticMemory) -> SemanticMemory:
        if self._embedding is None:
            return await self._store_semantic_sparse_only(memory)
        v, e = self._vec()
        bound = self._bind_scope(memory)
        stored = await store_semantic(bound, v, self._config, e, self._cache)
        from myrm_agent_harness.toolkits.memory.ephemeral_delta.notify import (
            record_ephemeral_memory_delta,
        )

        record_ephemeral_memory_delta(key=f"memory:{stored.id}", value=stored.content)
        await self._record_exact_fact_if_needed(stored)
        return stored

    async def _store_semantics_batch(self, memories: list[SemanticMemory]) -> list[SemanticMemory]:
        if self._embedding is None:
            return await self._store_semantics_sparse_only(memories)
        v, e = self._vec()
        bound_memories = [self._bind_scope(memory) for memory in memories]
        stored_list = await store_semantics_batch(
            bound_memories,
            v,
            self._config,
            e,
            self._cache,
        )
        from myrm_agent_harness.toolkits.memory.ephemeral_delta.notify import (
            record_ephemeral_memory_delta,
        )

        for stored in stored_list:
            record_ephemeral_memory_delta(key=f"memory:{stored.id}", value=stored.content)
        for stored in stored_list:
            await self._record_exact_fact_if_needed(stored)
        return stored_list

    async def _store_episodic(self, memory: EpisodicMemory) -> EpisodicMemory:
        if self._embedding is None:
            return await self._store_episodic_sparse_only(memory)
        v, e = self._vec()
        return await store_episodic(self._bind_scope(memory), v, self._config, e, self._cache, self._graph)

    async def _store_episodics_batch(self, memories: list[EpisodicMemory]) -> list[EpisodicMemory]:
        if self._embedding is None:
            return await self._store_episodics_sparse_only(memories)
        v, e = self._vec()
        return await store_episodics_batch(
            [self._bind_scope(memory) for memory in memories],
            v,
            self._config,
            e,
            self._cache,
            self._graph,
        )

    async def _record_exact_fact_if_needed(self, memory: SemanticMemory) -> None:
        """Mirror identifier-bearing memories into the relational exact-fact index (fail-open)."""
        if (
            self._relational is not None
            and hasattr(self._relational, "record_exact_fact")
            and (memory.is_exact_fact or memory.exact_identifiers)
        ):
            try:
                await self._relational.record_exact_fact(
                    memory_id=memory.id,
                    user_id=memory.user_id,
                    content=memory.content,
                    identifiers=memory.exact_identifiers,
                    primary_namespace=memory.scope.primary_namespace if memory.scope else "",
                    namespaces=memory.scope.namespaces if memory.scope else None,
                )
            except Exception as err:
                logger.warning("Failed to record exact fact in relational store: %s", err)

    def _sparse_only_vector(self) -> BM25SparseIndexStore:
        """Return the sparse-capable vector backend for embeddings-less writes.

        A missing sparse-capable backend keeps the previous fail-fast
        behaviour: without an embedding backend and without a sparse mirror
        there is nowhere to persist the memory.
        """
        vector = self._vector
        if vector is None or not isinstance(vector, BM25SparseIndexStore):
            raise MemoryError("Vector + Embedding backends required")
        return vector

    async def _store_semantic_sparse_only(self, memory: SemanticMemory) -> SemanticMemory:
        """Sparse-only semantic write for embeddings-less deployments.

        Without an embedding backend the dense path cannot run; the memory
        goes to the BM25 sparse mirror instead, which becomes the collection's
        authoritative store and is served by the existing BM25 fan-out.
        """
        vector = self._sparse_only_vector()
        bound = self._bind_scope(memory)
        await vector.upsert_sparse_only(self._config.semantic_collection, [semantic_to_doc(bound)])
        from myrm_agent_harness.toolkits.memory.ephemeral_delta.notify import (
            record_ephemeral_memory_delta,
        )

        record_ephemeral_memory_delta(key=f"memory:{bound.id}", value=bound.content)
        await self._record_exact_fact_if_needed(bound)
        return bound

    async def _store_semantics_sparse_only(self, memories: list[SemanticMemory]) -> list[SemanticMemory]:
        """Batch companion to ``_store_semantic_sparse_only``."""
        vector = self._sparse_only_vector()
        bound_memories = [self._bind_scope(memory) for memory in memories]
        await vector.upsert_sparse_only(
            self._config.semantic_collection,
            [semantic_to_doc(memory) for memory in bound_memories],
        )
        from myrm_agent_harness.toolkits.memory.ephemeral_delta.notify import (
            record_ephemeral_memory_delta,
        )

        for stored in bound_memories:
            record_ephemeral_memory_delta(key=f"memory:{stored.id}", value=stored.content)
            await self._record_exact_fact_if_needed(stored)
        return bound_memories

    async def _store_episodic_sparse_only(self, memory: EpisodicMemory) -> EpisodicMemory:
        """Sparse-only episodic write for embeddings-less deployments."""
        vector = self._sparse_only_vector()
        bound = self._bind_scope(memory)
        await vector.upsert_sparse_only(self._config.episodic_collection, [episodic_to_doc(bound)])
        return bound

    async def _store_episodics_sparse_only(self, memories: list[EpisodicMemory]) -> list[EpisodicMemory]:
        """Batch companion to ``_store_episodic_sparse_only``."""
        vector = self._sparse_only_vector()
        bound_memories = [self._bind_scope(memory) for memory in memories]
        await vector.upsert_sparse_only(
            self._config.episodic_collection,
            [episodic_to_doc(memory) for memory in bound_memories],
        )
        return bound_memories

    async def _store_conversations_batch(self, memories: list[ConversationMemory]) -> list[ConversationMemory]:
        from myrm_agent_harness.toolkits.memory._internal.storage import (
            store_conversations_batch,
        )

        v, e = self._vec()
        return await store_conversations_batch(
            [self._bind_scope(memory) for memory in memories],
            v,
            self._config,
            e,
            self._cache,
        )

    async def _store_procedural(self, memory: ProceduralMemory) -> ProceduralMemory:
        return await self._rel().create_rule(memory)

    async def _store_procedurals_batch(self, memories: list[ProceduralMemory]) -> list[ProceduralMemory]:
        return [await self._rel().create_rule(m) for m in memories]

    async def _run_consolidation_safe(self, cfg: ConsolidationConfig) -> None:
        """Run consolidation in background, swallowing all exceptions."""
        try:
            from myrm_agent_harness.toolkits.memory.strategies.consolidation import (
                run_consolidation,
                should_consolidate,
            )

            assert self._consolidation_llm is not None
            if not await should_consolidate(self, cfg):
                return
            await run_consolidation(
                self,
                self._consolidation_llm,
                cfg,
                on_conflict=self._on_conflict,
                on_complete=self._on_consolidation_complete,
            )
            self._stores_since_consolidation = 0
        except Exception as e:
            logger.warning("Background consolidation failed (non-fatal): %s", e)

    async def _warmup_embedding_cache(self) -> None:
        """Preload embeddings for recent memories into cache to eliminate cold-start latency.

        Runs asynchronously in background without blocking initialization.
        Collections are loaded in parallel for faster warmup.
        """
        if self._vector is None or self._embedding is None or self._cache is None:
            return

        try:
            limit = self._config.dedup.warmup_limit
            collections = [
                self._config.semantic_collection,
                self._config.episodic_collection,
            ]

            async def warmup_collection(collection: str) -> int:
                try:
                    exists = await self._vector.collection_exists(collection)
                    if not exists:
                        return 0

                    docs, _ = await self._vector.scroll(collection, limit=limit, filters={"archived": False})
                    if not docs:
                        return 0

                    texts = []
                    for doc in docs:
                        if hasattr(doc, "content"):
                            texts.append(doc.content)
                        elif isinstance(doc, dict) and "content" in doc:
                            texts.append(doc["content"])
                        elif hasattr(doc, "payload") and doc.payload and "content" in doc.payload:
                            texts.append(doc.payload["content"])

                    if not texts:
                        return 0
                    from myrm_agent_harness.toolkits.memory._internal.storage import (
                        embed_batch,
                    )

                    await embed_batch(texts, self._embedding, self._cache)
                    logger.info("Warmed up %d embeddings from %s", len(texts), collection)
                    return len(texts)
                except Exception as e:
                    logger.warning("Warmup failed for %s: %s", collection, e)
                    return 0

            results = await asyncio.gather(*[warmup_collection(c) for c in collections])
            total = sum(results)
            if total > 0:
                logger.info("Embedding cache warmup completed: %d embeddings preloaded", total)
        except Exception as e:
            logger.warning("Embedding cache warmup failed: %s", e)
