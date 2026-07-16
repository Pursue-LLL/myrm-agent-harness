"""Maintenance-side orchestration for health assessment and maintenance cycles.


[INPUT]
- memory._internal.maintenance::{run_forgetting, dedup_semantics, compile_claim_graph, ...} (POS: stateless maintenance operations)
- memory.strategies.consolidation::run_consolidation (POS: cross-session memory consolidation)

[OUTPUT]
- MaintenanceService: Maintenance orchestrator (health scoring, snapshot collection, maintenance cycles)
- MaintenanceConsolidationResult: Result data class for consolidation outcomes

[POS]
Maintenance-side orchestration. Handles health assessment, snapshot collection,
and maintenance cycles (dedup, forgetting, consolidation). Not part of the public API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory._internal.maintenance import (
    compile_claim_graph,
    evaporate_task_digests,
    run_forgetting,
    sweep_orphaned_blobs,
)
from myrm_agent_harness.toolkits.memory.config import ConsolidationConfig, MemoryConfig
from myrm_agent_harness.toolkits.memory.health import (
    HealthScore,
    MaintenanceReport,
    MemorySnapshot,
    NeglectedMemory,
    detect_neglected,
)
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphStoreProtocol
from myrm_agent_harness.toolkits.memory.protocols.relational import (
    RelationalStoreProtocol,
)
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
from myrm_agent_harness.toolkits.memory.types import AnyMemory, MemoryType

logger = logging.getLogger(__name__)

CountMemoriesFunc = Callable[[MemoryType], Awaitable[int]]
ListMemoriesFunc = Callable[[MemoryType, int], Awaitable[list[AnyMemory]]]
ComputeHealthFunc = Callable[[], Awaitable[HealthScore]]
ScrollAllFunc = Callable[[], Awaitable[list[AnyMemory]]]


class MaintenanceConsolidationResult(tuple[int, int, int, int, tuple[str, ...]]):
    __slots__ = ()

    @property
    def merged(self) -> int:
        return self[0]

    @property
    def corrected(self) -> int:
        return self[1]

    @property
    def updated(self) -> int:
        return self[2]

    @property
    def errors(self) -> int:
        return self[3]

    @property
    def insights(self) -> tuple[str, ...]:
        return self[4]


class MaintenanceService:
    """Owns maintenance orchestration that should not stay in MemoryManager."""

    __slots__ = ("_config", "_graph", "_namespaces", "_relational", "_vector")

    def __init__(
        self,
        *,
        config: MemoryConfig,
        vector: VectorStoreProtocol | None,
        graph: GraphStoreProtocol | None,
        relational: RelationalStoreProtocol | None = None,
        namespaces: list[str] | None = None,
    ) -> None:
        self._config = config
        self._vector = vector
        self._graph = graph
        self._relational = relational
        self._namespaces = namespaces

    async def collect_snapshot(self, *, count_memories_func: CountMemoriesFunc) -> MemorySnapshot | None:
        try:
            semantic = await count_memories_func(MemoryType.SEMANTIC)
            episodic = await count_memories_func(MemoryType.EPISODIC)
            return MemorySnapshot(semantic=semantic, episodic=episodic)
        except Exception as exc:
            logger.warning("Snapshot collection failed: %s", exc)
            return None

    async def scroll_all_memories(self, *, list_memories_func: ListMemoriesFunc) -> list[AnyMemory]:
        result: list[AnyMemory] = []
        for memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC):
            try:
                result.extend(await list_memories_func(memory_type, 5000))
            except Exception as exc:
                logger.warning(
                    "_scroll_all_memories: failed to list %s: %s",
                    memory_type.value,
                    exc,
                )
        return result

    async def compute_health_score(
        self,
        *,
        count_memories_func: CountMemoriesFunc,
        list_memories_func: ListMemoriesFunc,
    ) -> HealthScore:
        from myrm_agent_harness.toolkits.memory.health import (
            _COHERENCE_SAMPLE_LIMIT,
            _HealthInput,
            compute_health,
        )
        from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
            ForgettableMemory,
        )

        health_input = _HealthInput(has_graph=self._graph is not None, forgetting_config=self._config.forgetting)

        all_memories: list[ForgettableMemory] = []
        for memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC):
            try:
                all_memories.extend(await list_memories_func(memory_type, 5000))  # type: ignore[arg-type]
            except Exception as exc:
                logger.warning("Health: failed to list %s: %s", memory_type.value, exc)

        health_input.memories = all_memories

        for memory_type in MemoryType:
            if memory_type == MemoryType.TASK_DIGEST:
                continue
            count = 0
            with contextlib.suppress(Exception):
                count = await count_memories_func(memory_type)
            health_input.type_counts[memory_type.value] = count

            if count > 0:
                try:
                    recent = await list_memories_func(memory_type, 1)
                    if recent:
                        health_input.type_latest_update[memory_type.value] = recent[0].updated_at
                except Exception:
                    pass

        if self._graph is not None and all_memories:
            sample = all_memories[:_COHERENCE_SAMPLE_LIMIT]

            async def has_relations(memory_id: str) -> bool:
                try:
                    return bool(await self._graph.get_related_nodes(memory_id))
                except Exception:
                    return False

            results = await asyncio.gather(*[has_relations(memory.id) for memory in sample])
            health_input.coherent_count = sum(results)
            health_input.coherence_sample_size = len(sample)

        return compute_health(health_input)

    async def run_cycle(
        self,
        *,
        force: bool,
        lock: asyncio.Lock,
        consolidation_enabled: bool,
        collect_snapshot_func: Callable[[], Awaitable[MemorySnapshot | None]],
        compute_health_func: ComputeHealthFunc,
        scroll_all_memories_func: ScrollAllFunc,
        run_consolidation_func: Callable[[ConsolidationConfig, bool], Awaitable[MaintenanceConsolidationResult]],
        preference_rebuild_func: Callable[[], Awaitable[tuple[int, int, int]]] | None = None,
        staleness_review_llm: Callable[[str, str], Awaitable[str]] | None = None,
    ) -> MaintenanceReport:
        if lock.locked():
            return MaintenanceReport(skipped=True, skip_reason="already running")

        async with lock:
            start = datetime.now(UTC)
            before = await collect_snapshot_func()

            consolidation_merged = 0
            consolidation_corrected = 0
            consolidation_updated = 0
            consolidation_errors = 0
            consolidation_insights: tuple[str, ...] = ()
            digests_evaporated = 0
            claims_compiled = 0

            if consolidation_enabled:
                try:
                    consolidation = await run_consolidation_func(self._config.consolidation, force)
                    consolidation_merged = consolidation.merged
                    consolidation_corrected = consolidation.corrected
                    consolidation_updated = consolidation.updated
                    consolidation_errors = consolidation.errors
                    consolidation_insights = consolidation.insights
                except Exception as exc:
                    logger.warning("Maintenance consolidation failed: %s", exc)
                    consolidation_errors = 1

            forgotten_count = 0
            archived_count = 0
            blobs_swept = 0
            if self._vector is not None:
                try:
                    blobs_swept = await sweep_orphaned_blobs(self._vector, self._config)
                except Exception as exc:
                    logger.warning("Maintenance blob GC failed: %s", exc)

                try:
                    digests_evaporated = await evaporate_task_digests(self._vector, self._config)
                except Exception as exc:
                    logger.warning("Maintenance digest evaporation failed: %s", exc)

                if self._graph is not None:
                    try:
                        claims_compiled = await compile_claim_graph(self._vector, self._graph, self._config)
                    except Exception as exc:
                        logger.warning("Maintenance claim graph compilation failed: %s", exc)

                try:
                    forgetting = await run_forgetting(
                        self._vector, self._config, self._graph,
                        relational=self._relational, namespaces=self._namespaces,
                    )
                    forgotten_count = forgetting.forgotten_count
                    archived_count = forgetting.archived_count
                except Exception as exc:
                    logger.warning("Maintenance forgetting failed: %s", exc)

            staleness_reviewed, staleness_removed, staleness_extended = 0, 0, 0
            if staleness_review_llm is not None and self._vector is not None:
                try:
                    all_for_staleness = await scroll_all_memories_func()
                    staleness_reviewed, staleness_removed, staleness_extended = await self._run_staleness_review(
                        all_for_staleness, staleness_review_llm
                    )
                except Exception as exc:
                    logger.warning("Maintenance staleness review failed: %s", exc)

            pref_promoted, pref_demoted, pref_dropped = 0, 0, 0
            if preference_rebuild_func is not None:
                try:
                    pref_promoted, pref_demoted, pref_dropped = await preference_rebuild_func()
                    if pref_promoted or pref_demoted or pref_dropped:
                        logger.info(
                            "Preference stability rebuild: promoted=%d demoted=%d dropped=%d",
                            pref_promoted,
                            pref_demoted,
                            pref_dropped,
                        )
                except Exception as exc:
                    logger.warning("Maintenance preference rebuild failed: %s", exc)

            after = await collect_snapshot_func()

            health: HealthScore | None = None
            try:
                health = await compute_health_func()
            except Exception as exc:
                logger.warning("Maintenance health check failed: %s", exc)

            neglected: tuple[NeglectedMemory, ...] = ()
            if self._vector is not None:
                try:
                    all_memories = await scroll_all_memories_func()
                    neglected = detect_neglected(
                        all_memories,
                        importance_threshold=self._config.neglect_importance_threshold,
                        stale_days=self._config.neglect_stale_days,
                        max_items=self._config.neglect_max_items,
                    )
                except Exception as exc:
                    logger.warning("Maintenance neglected detection failed: %s", exc)

            elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
            report = MaintenanceReport(
                consolidation_merged=consolidation_merged,
                consolidation_corrected=consolidation_corrected,
                consolidation_updated=consolidation_updated,
                consolidation_errors=consolidation_errors,
                digests_evaporated=digests_evaporated,
                claims_compiled=claims_compiled,
                forgotten_count=forgotten_count,
                archived_count=archived_count,
                staleness_reviewed=staleness_reviewed,
                staleness_removed=staleness_removed,
                staleness_extended=staleness_extended,
                blobs_swept=blobs_swept,
                neglected_memories=neglected,
                insights=consolidation_insights,
                before=before,
                after=after,
                health=health,
                duration_ms=elapsed_ms,
            )
            logger.info(
                "Maintenance complete: before=%s after=%s merged=%d corrected=%d updated=%d evaporated=%d claims=%d forgotten=%d archived=%d staleness=%d/%d/%d blobs_swept=%d neglected=%d insights=%d health=%s (%.0fms)",
                before.total if before else "N/A",
                after.total if after else "N/A",
                consolidation_merged,
                consolidation_corrected,
                consolidation_updated,
                digests_evaporated,
                claims_compiled,
                forgotten_count,
                archived_count,
                staleness_reviewed,
                staleness_removed,
                staleness_extended,
                blobs_swept,
                len(neglected),
                len(consolidation_insights),
                health.total if health else "N/A",
                elapsed_ms,
            )
            return report

    async def _run_staleness_review(
        self,
        all_memories: list[AnyMemory],
        llm_func: Callable[[str, str], Awaitable[str]],
    ) -> tuple[int, int, int]:
        """Run staleness review on memories that exceeded their TTL.

        Returns (reviewed_count, removed_count, extended_count).
        """
        from myrm_agent_harness.toolkits.memory.strategies.forgetting import ForgettableMemory
        from myrm_agent_harness.toolkits.memory.strategies.staleness_review import (
            StalenessReviewer,
            StalenessReviewConfig,
            select_stale_candidates,
        )
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemoryStatus, SemanticMemory
        from myrm_agent_harness.toolkits.vector.base import VectorDocument

        forgettable = [m for m in all_memories if isinstance(m, (SemanticMemory, EpisodicMemory))]
        config = StalenessReviewConfig()
        candidates = select_stale_candidates(forgettable, config)  # type: ignore[arg-type]

        if len(candidates) < config.min_candidates:
            return (0, 0, 0)

        reviewer = StalenessReviewer(llm_func, config)
        result = await reviewer.review(candidates)

        id_to_type: dict[str, type] = {m.id: type(m) for m in candidates}

        async def _update_metadata(mid: str, meta_patch: dict[str, object]) -> None:
            mem_cls = id_to_type.get(mid)
            coll = (
                self._config.episodic_collection
                if mem_cls is EpisodicMemory
                else self._config.semantic_collection
            )
            docs = await self._vector.get(coll, [mid])  # type: ignore[union-attr]
            if not docs:
                return
            doc = docs[0]
            meta = dict(doc.metadata)
            meta.update(meta_patch)
            await self._vector.upsert(coll, [VectorDocument(  # type: ignore[union-attr]
                id=doc.id, vector=doc.vector, content=doc.content, metadata=meta,
            )])

        if self._vector is not None:
            for mid in result.removed_ids:
                try:
                    await _update_metadata(mid, {
                        "status": MemoryStatus.ARCHIVED.value,
                        "archive_reason": "staleness_review",
                    })
                except Exception as exc:
                    logger.warning("Staleness review: failed to archive %s: %s", mid, exc)

            for mid, new_evd in result.extended_updates:
                try:
                    await _update_metadata(mid, {"expected_valid_days": new_evd})
                except Exception as exc:
                    logger.warning("Staleness review: failed to extend %s: %s", mid, exc)

            for mid, new_evd in result.keep_cooldown_updates:
                try:
                    await _update_metadata(mid, {"expected_valid_days": new_evd})
                except Exception as exc:
                    logger.warning("Staleness review: failed to cooldown %s: %s", mid, exc)

        if result.removed_count > 0 or result.extended_count > 0:
            logger.info(
                "Staleness review: reviewed=%d removed=%d extended=%d kept=%d",
                result.reviewed_count,
                result.removed_count,
                result.extended_count,
                result.kept_count,
            )

        return (result.reviewed_count, result.removed_count, result.extended_count)
