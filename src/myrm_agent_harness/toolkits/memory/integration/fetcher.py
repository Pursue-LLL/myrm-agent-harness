"""Integration Fetcher — concurrent pull scheduler with idempotent dedup.

[INPUT]
- IntegrationProvider (POS: external service data source protocol)
- VectorStoreProtocol (POS: vector storage for memory persistence)
- EmbeddingProtocol (POS: text → embedding generation)
- IntegrationTreeManager (POS: tree structure maintenance)

[OUTPUT]
- IntegrationFetcher: Orchestrates pulling data from providers, embedding,
  storing, and tree-attaching integration memories.

[POS]
Central scheduler that converts raw ``IntegrationLeaf`` records from
registered providers into ``IntegrationMemory`` entries stored in both
the vector and graph backends.  Deduplication is done by
``(provider, external_object_id)`` pairs, ensuring idempotent re-syncs.
"""

from __future__ import annotations

import asyncio
import logging
import time

from myrm_agent_harness.toolkits.memory.integration.protocols import IntegrationProvider
from myrm_agent_harness.toolkits.memory.integration.tree_manager import IntegrationTreeManager
from myrm_agent_harness.toolkits.memory.integration.types import (
    IntegrationLeaf,
    IntegrationSyncOutcome,
    IntegrationSyncResult,
    IntegrationTree,
)
from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument, VectorStoreProtocol
from myrm_agent_harness.toolkits.memory.types import IntegrationMemory, MemoryScope, MemoryType

logger = logging.getLogger(__name__)

_COLLECTION = "integration_memory"
_EMBED_BATCH_SIZE = 32
_MAX_CONCURRENT_PROVIDERS = 5
_PROVIDER_FETCH_TIMEOUT_S = 120


class IntegrationFetcher:
    """Pull data from registered providers and store as IntegrationMemory.

    Lifecycle: create → register_provider(s) → sync() / sync_provider().
    The fetcher does NOT own the lifecycle of the stores — they are
    injected from the memory system.
    """

    def __init__(
        self,
        vector_store: VectorStoreProtocol,
        embedding: EmbeddingProtocol,
        tree_manager: IntegrationTreeManager,
        *,
        scope: MemoryScope | None = None,
    ) -> None:
        self._vs = vector_store
        self._emb = embedding
        self._tree = tree_manager
        self._scope = scope or MemoryScope()
        self._providers: dict[str, IntegrationProvider] = {}
        self._cursors: dict[str, str | None] = {}
        self._known_external_ids: set[str] = set()

    def register_provider(self, provider: IntegrationProvider) -> None:
        self._providers[provider.provider_id] = provider

    def unregister_provider(self, provider_id: str) -> None:
        self._providers.pop(provider_id, None)

    @property
    def provider_ids(self) -> list[str]:
        return list(self._providers)

    async def sync(self, *, max_items_per_provider: int = 200) -> list[IntegrationSyncResult]:
        """Sync all registered providers concurrently."""
        sem = asyncio.Semaphore(_MAX_CONCURRENT_PROVIDERS)

        async def _bounded(pid: str) -> IntegrationSyncResult:
            async with sem:
                return await self.sync_provider(pid, max_items=max_items_per_provider)

        tasks = [_bounded(pid) for pid in self._providers]
        return list(await asyncio.gather(*tasks, return_exceptions=False))

    async def sync_provider(
        self,
        provider_id: str,
        *,
        account_key: str = "",
        max_items: int = 200,
    ) -> IntegrationSyncResult:
        """Sync a single provider.  Idempotent — safe to call repeatedly."""
        t0 = time.monotonic()
        provider = self._providers.get(provider_id)
        if provider is None:
            return IntegrationSyncResult(
                tree_id="",
                provider=provider_id,
                account_key=account_key,
                failed=1,
                errors=[f"Provider '{provider_id}' not registered"],
                elapsed_seconds=0.0,
            )

        tree = await self._tree.get_or_create_tree(
            provider=provider_id,
            account_key=account_key,
        )

        cursor_key = f"{provider_id}::{account_key}"
        since_cursor = self._cursors.get(cursor_key)
        if since_cursor is None:
            since_cursor = await provider.get_sync_cursor(account_key=account_key)

        try:
            leaves = await asyncio.wait_for(
                provider.fetch(
                    account_key=account_key,
                    since_cursor=since_cursor,
                    max_items=max_items,
                ),
                timeout=_PROVIDER_FETCH_TIMEOUT_S,
            )
        except TimeoutError:
            logger.error("Fetch timed out for provider=%s after %ds", provider_id, _PROVIDER_FETCH_TIMEOUT_S)
            return IntegrationSyncResult(
                tree_id=tree.id,
                provider=provider_id,
                account_key=account_key,
                failed=1,
                errors=[f"Provider '{provider_id}' fetch timed out after {_PROVIDER_FETCH_TIMEOUT_S}s"],
                elapsed_seconds=time.monotonic() - t0,
            )
        except Exception as exc:
            logger.error("Fetch failed for provider=%s: %s", provider_id, exc)
            return IntegrationSyncResult(
                tree_id=tree.id,
                provider=provider_id,
                account_key=account_key,
                failed=1,
                errors=[str(exc)],
                elapsed_seconds=time.monotonic() - t0,
            )

        created, updated, skipped, failed = 0, 0, 0, 0
        errors: list[str] = []
        new_items: list[dict[str, str]] = []

        for batch_start in range(0, len(leaves), _EMBED_BATCH_SIZE):
            batch = leaves[batch_start : batch_start + _EMBED_BATCH_SIZE]
            outcomes = await self._ingest_batch(batch, tree)
            for outcome, err, item_data in outcomes:
                if outcome == IntegrationSyncOutcome.CREATED:
                    created += 1
                    if item_data:
                        new_items.append(item_data)
                elif outcome == IntegrationSyncOutcome.UPDATED:
                    updated += 1
                    if item_data:
                        new_items.append(item_data)
                elif outcome == IntegrationSyncOutcome.SKIPPED:
                    skipped += 1
                else:
                    failed += 1
                    if err:
                        errors.append(err)

        new_cursor = await provider.get_sync_cursor(account_key=account_key)
        self._cursors[cursor_key] = new_cursor

        elapsed = time.monotonic() - t0
        logger.info(
            "Sync complete: provider=%s created=%d updated=%d skipped=%d failed=%d (%.1fs)",
            provider_id,
            created,
            updated,
            skipped,
            failed,
            elapsed,
        )

        return IntegrationSyncResult(
            tree_id=tree.id,
            provider=provider_id,
            account_key=account_key,
            created=created,
            updated=updated,
            skipped=skipped,
            failed=failed,
            errors=errors,
            new_items=new_items,
            elapsed_seconds=elapsed,
        )

    # ── Internal ─────────────────────────────────────────────────────

    async def _ingest_batch(
        self,
        leaves: list[IntegrationLeaf],
        tree: IntegrationTree,
    ) -> list[tuple[IntegrationSyncOutcome, str, dict[str, str]]]:
        """Embed, dedup, store, and attach a batch of leaves."""
        texts = [self._leaf_to_text(lf) for lf in leaves]
        try:
            embeddings = await self._emb.embed_batch(texts)
        except Exception as exc:
            return [(IntegrationSyncOutcome.FAILED, f"Embedding error: {exc}", {})] * len(leaves)

        results: list[tuple[IntegrationSyncOutcome, str, dict[str, str]]] = []
        docs: list[VectorDocument] = []
        memories: list[IntegrationMemory] = []
        pending_known_keys: list[tuple[str, str]] = []

        for leaf, emb, text in zip(leaves, embeddings, texts, strict=True):
            item_data = {"text": text, "type": leaf.source_type, "title": leaf.title}
            if self._is_known(leaf.provider, leaf.external_object_id):
                results.append((IntegrationSyncOutcome.SKIPPED, "", item_data))
                continue

            mem = self._leaf_to_memory(leaf, emb, tree.id)
            pending_known_keys.append((leaf.provider, leaf.external_object_id))
            memories.append(mem)
            docs.append(
                VectorDocument(
                    id=mem.id,
                    content=text,
                    vector=emb,
                    metadata={
                        "memory_type": MemoryType.INTEGRATION,
                        "provider": leaf.provider,
                        "source_type": leaf.source_type,
                        "external_object_id": leaf.external_object_id,
                        "tree_id": tree.id,
                    },
                )
            )
            results.append((IntegrationSyncOutcome.CREATED, "", item_data))

        if docs:
            try:
                await self._vs.upsert(_COLLECTION, docs)
            except Exception as exc:
                return [(IntegrationSyncOutcome.FAILED, f"Vector upsert error: {exc}", {})] * len(leaves)

            for provider, ext_id in pending_known_keys:
                self._mark_known(provider, ext_id)

            for mem in memories:
                try:
                    await self._tree.attach_leaf(tree, mem)
                except Exception as exc:
                    logger.warning("Tree attach failed for %s: %s", mem.id, exc)

        return results

    def _is_known(self, provider: str, external_object_id: str) -> bool:
        if not external_object_id:
            return False
        dedup_key = f"{provider}::{external_object_id}"
        return dedup_key in self._known_external_ids

    def _mark_known(self, provider: str, external_object_id: str) -> None:
        if external_object_id:
            self._known_external_ids.add(f"{provider}::{external_object_id}")

    def _leaf_to_memory(self, leaf: IntegrationLeaf, embedding: list[float], tree_id: str) -> IntegrationMemory:
        return IntegrationMemory(
            id=leaf.id,
            content=leaf.content or leaf.summary or leaf.title,
            embedding=embedding,
            provider=leaf.provider,
            account_key=leaf.account_key,
            account_label=leaf.account_label,
            source_type=leaf.source_type,
            external_object_id=leaf.external_object_id,
            external_object_type=leaf.external_object_type,
            title=leaf.title,
            summary=leaf.summary,
            tags=leaf.tags,
            observed_at=leaf.observed_at,
            tree_id=tree_id,
            metadata=leaf.metadata,
            scope=self._scope,
        )

    @staticmethod
    def _leaf_to_text(leaf: IntegrationLeaf) -> str:
        parts: list[str] = []
        if leaf.title:
            parts.append(leaf.title)
        if leaf.content:
            parts.append(leaf.content)
        elif leaf.summary:
            parts.append(leaf.summary)
        return "\n".join(parts) if parts else leaf.external_object_id or ""
