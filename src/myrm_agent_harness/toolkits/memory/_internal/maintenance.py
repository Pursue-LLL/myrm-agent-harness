"""Background maintenance operations for memory lifecycle.


[INPUT]
- memory._internal.storage::{storage conversion functions} (POS: internal vector storage operations)
- memory._internal.maintenance_claim_compile::compile_claim_graph (POS: Claim graph compilation from evaporated L2 digests)
- memory._internal.maintenance_claim_support::search_claim_graph (POS: Claim node graph search)
- memory._internal.maintenance_enrichment::enrich_with_graph (POS: Graph enrichment for memory search)
- memory.protocols.vector::{VectorDocument, VectorStoreProtocol} (POS: vector store protocol)
- memory.protocols.graph::GraphStoreProtocol (POS: graph store protocol)
- memory.types::{memory data models} (POS: memory data models)

[OUTPUT]
- dedup_semantics: vector dedup (similarity ≥0.95)
- run_forgetting: five-dimension forgetting execution
- bump_access_counts: async access count update
- enrich_with_graph: re-export from maintenance_enrichment
- compile_claim_graph: re-export from maintenance_claim_compile
- evaporate_task_digests: task digest evaporation
- sweep_orphaned_blobs: orphaned BLOB garbage collection
- _search_claim_graph: alias of search_claim_graph for internal/tests

[POS]
Stateless background maintenance orchestration. Coordinates dedup, forgetting, access tracking,
task digest evaporation, and blob GC. Delegates claim graph and enrichment to sibling modules.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.storage import (
    _user_filter,
    doc_to_episodic,
    doc_to_semantic,
    embed_single,
    episodic_to_doc,
    semantic_to_doc,
)
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import (
    ClaimConflictState,
    ClaimGraphState,
    DigestKind,
    EpisodicMemory,
    EvaporationState,
    MemorySearchResult,
    MemoryTier,
    ProceduralMemory,
    SemanticMemory,
)
from myrm_agent_harness.toolkits.memory._internal.maintenance_claim_compile import compile_claim_graph  # noqa: F401 — re-export
from myrm_agent_harness.toolkits.memory._internal.maintenance_claim_support import (
    search_claim_graph as _search_claim_graph,  # noqa: F401 — re-export
)
from myrm_agent_harness.toolkits.memory._internal.maintenance_enrichment import enrich_with_graph  # noqa: F401 — re-export

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.protocols.cache import (
        EmbeddingCacheProtocol,
    )
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.graph import GraphStoreProtocol
    from myrm_agent_harness.toolkits.memory.protocols.relational import (
        RelationalStoreProtocol,
    )
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
    from myrm_agent_harness.toolkits.memory.strategies.forgetting import (  # noqa: F401
        ForgettingConfig,
        ForgettingResult,
        ForgettingStrategy,
    )

logger = logging.getLogger(__name__)



async def dedup_semantics(
    memories: list[SemanticMemory],
    vector: VectorStoreProtocol,
    embedding: EmbeddingProtocol,
    config: MemoryConfig,
    cache: EmbeddingCacheProtocol | None,
) -> list[SemanticMemory]:
    """Remove near-duplicate SemanticMemory entries before storing.

    Parallel embedding + parallel search for efficiency.
    Memories with similarity >= 0.95 to an existing entry are silently dropped.
    """
    threshold = 0.95

    for mem in memories:
        if mem.embedding is None:
            mem.embedding = await embed_single(mem.content, embedding, cache)

    async def _is_dup(mem: SemanticMemory) -> bool:
        assert mem.embedding is not None
        try:
            hits = await vector.search(
                config.semantic_collection,
                mem.embedding,
                limit=1,
                filters=None,
                score_threshold=threshold,
            )
            return bool(hits)
        except Exception as exc:
            logger.warning("Dedup search failed (non-fatal): %s", exc)
            return False

    dup_flags = await asyncio.gather(*[_is_dup(m) for m in memories])
    skipped = sum(dup_flags)
    if skipped:
        total = len(memories)
        rate = skipped / total * 100 if total > 0 else 0
        logger.warning("Dedup: skipped %d/%d near-duplicates (rate=%.1f%%)", skipped, total, rate)
    return [m for m, is_dup in zip(memories, dup_flags, strict=False) if not is_dup]


async def run_forgetting(
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    graph: GraphStoreProtocol | None = None,
    relational: RelationalStoreProtocol | None = None,
    namespaces: list[str] | None = None,
) -> ForgettingResult:
    """Scan and process low-retention memories based on ForgettingConfig.mode.

    Modes:
        DELETE  — permanently remove from vector store and graph
        ARCHIVE — mark as archived (metadata update), preserve graph relations
        MARK    — log candidates only, no mutation

    Covers all ForgettableMemory types: Semantic/Episodic (vector store) and
    Procedural (relational store). Pinned and CRITICAL-priority rules are
    protected by ForgettingStrategy.
    """
    from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
        ForgettingConfig,  # noqa: F401
        ForgettingMode,
        ForgettingResult,
        ForgettingStrategy,
    )

    fg_cfg: ForgettingConfig = config.forgetting
    result = ForgettingResult()

    try:
        strategy = ForgettingStrategy(fg_cfg)
        now_iso = datetime.now(UTC).isoformat()

        for collection, converter, estimate_rels in (
            (config.semantic_collection, doc_to_semantic, True),
            (config.episodic_collection, doc_to_episodic, False),
        ):
            docs, _ = await vector.scroll(
                collection,
                limit=fg_cfg.max_forget_per_run * 2,
                filters=None,
            )
            memories = [converter(d) for d in docs]
            rel_counts: dict[str, int] = {}
            if estimate_rels:
                rel_counts = await _estimate_relation_counts(
                    memories,
                    collection,
                    vector,
                )
            candidates = strategy.select_candidates(memories, rel_counts)
            if not candidates:
                continue

            ids = [mem.id for mem, _ in candidates]

            if fg_cfg.mode == ForgettingMode.DELETE:
                result.forgotten_count += await vector.delete(collection, ids)
                result.forgotten_ids.extend(ids)
                if graph is not None:
                    for memory_id in ids:
                        try:
                            await graph.delete_subgraph(memory_id)
                        except Exception as e:
                            logger.warning("Graph cleanup failed for %s: %s", memory_id, e)
                            result.errors.append((memory_id, str(e)))

            elif fg_cfg.mode == ForgettingMode.ARCHIVE:
                docs_by_id = {d.id: d for d in docs}
                archive_docs: list[VectorDocument] = []
                for mem, score in candidates:
                    doc = docs_by_id.get(mem.id)
                    if doc is None:
                        continue
                    doc.metadata["status"] = "archived"
                    doc.metadata["archived_at"] = now_iso
                    doc.metadata["archive_reason"] = f"retention={score.total_score:.3f}"
                    archive_docs.append(doc)
                if archive_docs:
                    await vector.upsert(collection, archive_docs)
                result.archived_count += len(archive_docs)
                result.archived_ids.extend(ids)

            else:
                logger.info(
                    "Forgetting MARK mode: %d candidates in %s (ids: %s)",
                    len(candidates),
                    collection,
                    ids[:5],
                )

        if relational is not None:
            await _forget_procedural_rules(relational, strategy, fg_cfg, result, namespaces)

        if result.forgotten_count:
            logger.warning("Forgetting DELETE: removed %d memories", result.forgotten_count)
        if result.archived_count:
            logger.warning("Forgetting ARCHIVE: archived %d memories", result.archived_count)

    except Exception as e:
        logger.warning("Forgetting scan failed (non-fatal): %s", e)

    return result


async def _forget_procedural_rules(
    relational: RelationalStoreProtocol,
    strategy: ForgettingStrategy,
    fg_cfg: ForgettingConfig,
    result: ForgettingResult,
    namespaces: list[str] | None,
) -> None:
    """Apply forgetting strategy to ProceduralMemory stored in relational DB."""
    from myrm_agent_harness.toolkits.memory.strategies.forgetting import ForgettingMode
    from myrm_agent_harness.toolkits.memory.types import ToolRulePriority

    try:
        rules = await relational.list_rules(
            active_only=True,
            limit=fg_cfg.max_forget_per_run * 2,
            namespaces=namespaces,
        )
    except Exception as e:
        logger.warning("Forgetting: failed to fetch procedural rules: %s", e)
        return

    rules = [r for r in rules if not r.is_user_locked]

    for rule in rules:
        if rule.tool_rule_priority == ToolRulePriority.CRITICAL:
            rule.importance = max(rule.importance, 0.95)

    candidates = strategy.select_candidates(rules, {})
    if not candidates:
        return

    for rule, score in candidates:
        try:
            if fg_cfg.mode == ForgettingMode.DELETE:
                if await relational.delete_rule(rule.id):
                    result.forgotten_count += 1
                    result.forgotten_ids.append(rule.id)
            elif fg_cfg.mode == ForgettingMode.ARCHIVE:
                rule.is_active = False
                rule.metadata["archived_at"] = datetime.now(UTC).isoformat()
                rule.metadata["archive_reason"] = f"retention={score.total_score:.3f}"
                await relational.update_rule(rule.id, rule)
                result.archived_count += 1
                result.archived_ids.append(rule.id)
            else:
                logger.info("Forgetting MARK mode: procedural rule %s (score=%.3f)", rule.id, score.total_score)
        except Exception as e:
            logger.warning("Forgetting procedural rule %s failed: %s", rule.id, e)
            result.errors.append((rule.id, str(e)))


async def evaporate_task_digests(
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    *,
    limit: int = 100,
) -> int:
    """Advance pending task digests from L2 pending state to evaporated state.

    This is the minimal lifecycle hook for future L3 compilation. It does not
    build a claim graph yet; it only marks digests as consumed by the
    maintenance pipeline so later compilers can process incrementally.
    """
    filters = _user_filter()
    filters["event_type"] = "task_digest"
    filters["evaporation_state"] = EvaporationState.PENDING.value

    docs, _ = await vector.scroll(
        config.episodic_collection,
        limit=limit,
        filters=filters,
    )
    if not docs:
        return 0

    evaporated_at = datetime.now(UTC).isoformat()
    for doc in docs:
        doc.metadata["memory_tier"] = MemoryTier.L2.value
        doc.metadata["digest_kind"] = DigestKind.TASK.value
        doc.metadata["evaporation_state"] = EvaporationState.EVAPORATED.value
        doc.metadata["evaporated_at"] = evaporated_at
        doc.metadata["claim_graph_state"] = ClaimGraphState.PENDING.value
        doc.metadata["claim_graph_conflict"] = ClaimConflictState.NONE.value

    await vector.upsert(config.episodic_collection, docs)
    return len(docs)


_RELATION_CONCURRENCY = 10


async def _estimate_relation_counts(
    memories: list[SemanticMemory] | list[EpisodicMemory],
    collection: str,
    vector: VectorStoreProtocol,
) -> dict[str, int]:
    """Approximate relation_count by counting vector neighbors (sim > 0.8).

    Only called for SemanticMemory. Concurrency is capped to avoid
    overwhelming the vector backend.
    """
    embeddable = [(m.id, m.embedding) for m in memories if getattr(m, "embedding", None)]
    if not embeddable:
        return {}

    sem = asyncio.Semaphore(_RELATION_CONCURRENCY)

    async def _count(mem_id: str, emb: list[float]) -> tuple[str, int]:
        async with sem:
            try:
                hits = await vector.search(
                    collection,
                    emb,
                    limit=5,
                    filters=None,
                    score_threshold=0.8,
                )
                return mem_id, max(len(hits) - 1, 0)
            except Exception:
                return mem_id, 0

    results = await asyncio.gather(*[_count(mid, emb) for mid, emb in embeddable])
    return dict(results)


async def bump_access_counts(
    results: list[MemorySearchResult],
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    relational: RelationalStoreProtocol | None = None,
) -> None:
    """Fire-and-forget: increment access_count for retrieved memories."""
    try:
        now = datetime.now(UTC)
        for r in results:
            mem = r.memory
            if isinstance(mem, (SemanticMemory, EpisodicMemory)):
                mem.access_count += 1
                mem.last_accessed_at = now
        sem_docs = [semantic_to_doc(r.memory) for r in results if isinstance(r.memory, SemanticMemory)]
        epi_docs = [episodic_to_doc(r.memory) for r in results if isinstance(r.memory, EpisodicMemory)]
        if sem_docs:
            await vector.upsert(config.semantic_collection, sem_docs)
        if epi_docs:
            await vector.upsert(config.episodic_collection, epi_docs)
        if relational:
            for r in results:
                mem = r.memory
                if isinstance(mem, ProceduralMemory):
                    mem.access_count += 1
                    mem.last_accessed_at = now
                    try:
                        await relational.update_rule(mem.id, mem)
                    except Exception as exc:
                        logger.debug("Procedural access count update skipped for %s: %s", mem.id, exc)
    except Exception as e:
        logger.warning("Access count update failed (non-fatal): %s", e)


async def sweep_orphaned_blobs(
    vector: VectorStoreProtocol,
    config: MemoryConfig,
) -> int:
    """Garbage collect orphaned external BLOB files.

    Scans the local blob directory and deletes any .gz files that are
    no longer referenced by active ConversationMemory entries in Qdrant.
    """
    import time
    from pathlib import Path

    if not config.blob_storage_enabled:
        return 0

    blob_dir = Path(config.blob_storage_path).expanduser().resolve()
    if not blob_dir.exists() or not blob_dir.is_dir():
        return 0

    # 1. Get all blob files on disk
    disk_blobs = set()
    now_ts = time.time()
    for f in blob_dir.glob("*.gz"):
        if f.is_file():
            # Grace period: skip files modified in the last hour to prevent race conditions
            # with concurrent writes that haven't been committed to Qdrant yet.
            if now_ts - f.stat().st_mtime < 3600:
                continue
            disk_blobs.add(f.stem)  # hash without .gz

    if not disk_blobs:
        return 0

    # 2. Scroll through Qdrant to find active blob pointers
    active_blobs = set()
    next_offset = 0
    while next_offset is not None:
        try:
            docs, next_offset = await vector.scroll(
                config.conversation_collection,
                limit=1000,
                offset=next_offset,
                filters=None,
            )
            if not docs:
                break

            for doc in docs:
                raw_exchange = doc.metadata.get("raw_exchange", "")
                if isinstance(raw_exchange, str) and raw_exchange.startswith("blob://"):
                    blob_hash = raw_exchange[len("blob://") :]
                    active_blobs.add(blob_hash)
        except Exception as e:
            logger.error("Blob GC scroll failed. Aborting GC to prevent data loss: %s", e)
            return 0

    # 3. Delete orphaned blobs
    orphans = disk_blobs - active_blobs
    deleted_count = 0
    for orphan in orphans:
        try:
            (blob_dir / f"{orphan}.gz").unlink(missing_ok=True)
            deleted_count += 1
        except Exception as e:
            logger.warning("Failed to delete orphaned blob %s: %s", orphan, e)

    if deleted_count > 0:
        logger.info("Blob GC: deleted %d orphaned blobs", deleted_count)

    return deleted_count

