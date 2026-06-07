"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations

import asyncio

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

    def _bind_scope(self, memory: AnyMemory) -> AnyMemory:
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
        v, e = self._vec()
        return await store_semantic(self._bind_scope(memory), v, self._config, e, self._cache)

    async def _store_semantics_batch(self, memories: list[SemanticMemory]) -> list[SemanticMemory]:
        v, e = self._vec()
        return await store_semantics_batch(
            [self._bind_scope(memory) for memory in memories],
            v,
            self._config,
            e,
            self._cache,
        )

    async def _store_episodic(self, memory: EpisodicMemory) -> EpisodicMemory:
        v, e = self._vec()
        return await store_episodic(self._bind_scope(memory), v, self._config, e, self._cache, self._graph)

    async def _store_episodics_batch(self, memories: list[EpisodicMemory]) -> list[EpisodicMemory]:
        v, e = self._vec()
        return await store_episodics_batch(
            [self._bind_scope(memory) for memory in memories],
            v,
            self._config,
            e,
            self._cache,
            self._graph,
        )

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
            await run_consolidation(self, self._consolidation_llm, cfg)
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
