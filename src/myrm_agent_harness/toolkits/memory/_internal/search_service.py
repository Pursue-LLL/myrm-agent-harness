"""Search-side orchestration for memory retrieval.


[INPUT]
- memory._internal.storage::{doc_to_*, load_context} (POS: internal vector storage operations)
- memory._internal.scope::{build_scope, apply_channel_affinity} (POS: scope and namespace helpers)
- memory.retriever::MemoryRetriever (POS: RRF retriever for memory search)

[OUTPUT]
- MemorySearchService: Search-side orchestrator (query cleanup, type routing, RRF fusion, graph enrichment, retrieval trace)

[POS]
Search-side orchestration for memory retrieval. Handles query cleanup, type routing,
RRF fusion, graph enrichment, and business-neutral retrieval trace emission. Not part of the public API.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from myrm_agent_harness.toolkits.memory._assistant_retrieval import search_conversation_two_pass
from myrm_agent_harness.toolkits.memory._internal.maintenance import bump_access_counts, enrich_with_graph
from myrm_agent_harness.toolkits.memory._internal.scope import apply_channel_affinity
from myrm_agent_harness.toolkits.memory._internal.storage import (
    embed_single,
    search_bm25,
    search_conversation,
    search_episodic,
    search_procedural,
    search_profile,
    search_semantic,
)
from myrm_agent_harness.toolkits.memory.adaptive import should_use_dual_channel
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.intent_recognizers import KeywordBasedRecognizer
from myrm_agent_harness.toolkits.memory.metrics import get_search_metrics
from myrm_agent_harness.toolkits.memory.observability import MemoryRetrievalTrace, MemoryTraceStep
from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol
from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphStoreProtocol
from myrm_agent_harness.toolkits.memory.protocols.relational import RelationalStoreProtocol
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
from myrm_agent_harness.toolkits.memory.query_analyzer import analyze_query, is_assistant_reference_query
from myrm_agent_harness.toolkits.memory.query_sanitizer import QuerySanitizer
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemorySearchResult, MemoryType

logger = logging.getLogger(__name__)

FTS5SearcherFunc = Callable[[str, int], Awaitable[list[MemorySearchResult]]]


def _log_background_task_failure(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    try:
        exc = task.exception()
    except Exception as err:
        logger.warning("Memory background task exception lookup failed: %s", err)
        return
    if exc is not None:
        logger.warning("Memory background task failed: %s", exc)


class MemorySearchService:
    """Owns query sanitization, source fan-out, fusion, and graph enrichment."""

    __slots__ = (
        "_cache",
        "_config",
        "_current_channel_id",
        "_embedding",
        "_fts5_searcher",
        "_graph",
        "_last_trace",
        "_namespaces",
        "_relational",
        "_retriever",
        "_vector",
    )

    def __init__(
        self,
        *,
        namespaces: list[str],
        current_channel_id: str | None,
        config: MemoryConfig,
        vector: VectorStoreProtocol | None,
        graph: GraphStoreProtocol | None,
        relational: RelationalStoreProtocol | None,
        embedding: EmbeddingProtocol | None,
        cache: EmbeddingCacheProtocol | None,
        retriever: MemoryRetriever,
        fts5_searcher: FTS5SearcherFunc | None,
    ) -> None:
        self._namespaces = list(namespaces)
        self._current_channel_id = current_channel_id
        self._config = config
        self._vector = vector
        self._graph = graph
        self._relational = relational
        self._embedding = embedding
        self._cache = cache
        self._retriever = retriever
        self._fts5_searcher = fts5_searcher
        self._last_trace: MemoryRetrievalTrace | None = None

    @property
    def last_trace(self) -> MemoryRetrievalTrace | None:
        return self._last_trace

    async def search(
        self,
        query: str,
        *,
        memory_types: list[MemoryType],
        memory_types_unspecified: bool,
        limit: int,
        use_rrf: bool,
        include_raw: bool,
        since: datetime | None = None,
        until: datetime | None = None,
        current_chat_id: str | None = None,
    ) -> list[MemorySearchResult]:
        trace_start = perf_counter()
        steps: list[MemoryTraceStep] = []
        sanitized_query = QuerySanitizer().sanitize(query)
        steps.append(
            MemoryTraceStep(
                phase="sanitize",
                title="query_sanitize",
                summary="Retrieval query sanitized before storage lookup.",
                input_count=1 if query else 0,
                output_count=1 if sanitized_query else 0,
                metadata={"changed": sanitized_query != query},
            )
        )
        claim_requested = self._graph is not None and (
            memory_types_unspecified or MemoryType.CLAIM in memory_types or MemoryType.SEMANTIC in memory_types
        )
        search_types = [memory_type for memory_type in memory_types if memory_type != MemoryType.CLAIM]
        runtime_config = self._resolve_runtime_config(sanitized_query)
        tracked_types = list(dict.fromkeys([*search_types, *([MemoryType.CLAIM] if claim_requested else [])]))
        metrics = get_search_metrics()
        steps.append(
            MemoryTraceStep(
                phase="route",
                title="type_route",
                summary="Memory types and claim graph eligibility resolved.",
                input_count=len(memory_types),
                output_count=len(tracked_types),
                metadata={"claim_requested": claim_requested, "use_rrf": use_rrf},
            )
        )

        with metrics.track_search(searched_types=tracked_types, current_chat_id=current_chat_id) as tracker:
            embed_start = perf_counter()
            query_vector = await self._embed_query_if_needed(sanitized_query, search_types)
            steps.append(
                MemoryTraceStep(
                    phase="embed",
                    status="success" if query_vector is not None else "skipped",
                    title="query_embedding",
                    summary="Dense query vector prepared when vector-backed memory types are searched.",
                    duration_ms=_elapsed_ms(embed_start),
                    input_count=1,
                    output_count=1 if query_vector is not None else 0,
                )
            )
            collect_start = perf_counter()
            result_lists = await self._collect_result_lists(
                query=sanitized_query,
                memory_types=search_types,
                limit=limit,
                include_raw=include_raw,
                config=runtime_config,
                query_vector=query_vector,
                since=since,
                until=until,
            )
            candidate_count = sum(len(result_list) for result_list in result_lists)
            steps.append(
                MemoryTraceStep(
                    phase="collect",
                    title="candidate_collect",
                    summary="Candidate memories collected from configured stores.",
                    duration_ms=_elapsed_ms(collect_start),
                    input_count=len(search_types),
                    output_count=candidate_count,
                    metadata={"result_lists": len(result_lists)},
                )
            )
            rank_start = perf_counter()
            query_context = analyze_query(sanitized_query)
            final = self._rank_results(
                result_lists=result_lists, query=sanitized_query, limit=limit, use_rrf=use_rrf, config=runtime_config,
                query_context=query_context,
            )
            steps.append(
                MemoryTraceStep(
                    phase="rank",
                    title="candidate_rank",
                    summary="Candidates fused, suppressed, diversified, and normalized.",
                    duration_ms=_elapsed_ms(rank_start),
                    input_count=candidate_count,
                    output_count=len(final),
                    metadata={"limit": limit, "use_rrf": use_rrf},
                )
            )
            if self._graph is not None and claim_requested:
                graph_start = perf_counter()
                final = await enrich_with_graph(
                    final,
                    sanitized_query,
                    limit,
                    self._graph,
                    self._vector,
                    runtime_config,
                    current_channel_id=self._current_channel_id,
                    namespaces=self._namespaces,
                )
                steps.append(
                    MemoryTraceStep(
                        phase="graph",
                        title="graph_enrich",
                        summary="Claim graph enrichment applied to retrieval candidates.",
                        duration_ms=_elapsed_ms(graph_start),
                        input_count=candidate_count,
                        output_count=len(final),
                    )
                )
            else:
                steps.append(
                    MemoryTraceStep(
                        phase="graph",
                        status="skipped",
                        title="graph_enrich",
                        summary="Graph enrichment skipped for this query.",
                        input_count=candidate_count,
                        output_count=len(final),
                    )
                )
            if not include_raw:
                final = self._strip_raw_exchange(final)
            tracker.record(final)
        self._last_trace = MemoryRetrievalTrace(
            id=uuid4().hex,
            query_preview=sanitized_query[:180],
            occurred_at=datetime.now(UTC),
            result_count=len(final),
            steps=[
                *steps,
                MemoryTraceStep(
                    phase="budget",
                    title="output_budget",
                    summary="Raw exchanges stripped when recall output requested a compact result.",
                    status="success" if not include_raw else "skipped",
                    duration_ms=_elapsed_ms(trace_start),
                    input_count=candidate_count if "candidate_count" in locals() else 0,
                    output_count=len(final),
                    metadata={"include_raw": include_raw},
                ),
            ],
        )
        return final

    def _resolve_runtime_config(self, query: str) -> MemoryConfig:
        if not self._config.retrieval.enable_intent_recognition:
            return self._config

        recognizer = self._config.retrieval.intent_recognizer or KeywordBasedRecognizer()
        result = recognizer.recognize(query)
        if result.confidence <= 0.5:
            return self._config

        adjusted_retrieval = replace(self._config.retrieval, type_weights=result.type_weights)
        return replace(self._config, retrieval=adjusted_retrieval)

    async def _embed_query_if_needed(self, query: str, memory_types: list[MemoryType]) -> list[float] | None:
        needs_vector = any(
            memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.CONVERSATION)
            for memory_type in memory_types
        )
        if not needs_vector or self._embedding is None:
            return None
        return await embed_single(query, self._embedding, self._cache)

    async def _collect_result_lists(
        self,
        *,
        query: str,
        memory_types: list[MemoryType],
        limit: int,
        include_raw: bool,
        config: MemoryConfig,
        query_vector: list[float] | None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[list[MemorySearchResult]]:
        tasks: list[asyncio.Task[list[MemorySearchResult]]] = []
        for memory_type in memory_types:
            self._append_type_search_tasks(
                tasks,
                memory_type=memory_type,
                query=query,
                limit=limit,
                include_raw=include_raw,
                config=config,
                query_vector=query_vector,
                since=since,
                until=until,
            )

        needs_vector = any(
            memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.CONVERSATION)
            for memory_type in memory_types
        )
        if self._vector is not None and needs_vector:
            tasks.append(
                asyncio.create_task(
                    search_bm25(
                        query,
                        self._vector,
                        config,
                        namespaces=self._namespaces,
                        since=since,
                        until=until,
                    )
                )
            )

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        result_lists: list[list[MemorySearchResult]] = []
        for result in raw_results:
            if isinstance(result, BaseException):
                logger.warning("Memory search error: %s", result)
            elif isinstance(result, list) and result:
                filtered = self._filter_results(result)
                if filtered:
                    result_lists.append(apply_channel_affinity(filtered, current_channel_id=self._current_channel_id))
        return result_lists

    @staticmethod
    def _filter_results(results: list[MemorySearchResult]) -> list[MemorySearchResult]:
        """Hide internal L2 task digests, archive checkpoints, and subsumed memories from normal recall results.

        Task digests are compilation artifacts for the L2 -> L3 pipeline.
        Archive checkpoints are internal prune milestones for pre-compaction inject.
        Subsumed memories are redundant memories that have been incorporated into skills/wiki.
        """
        filtered: list[MemorySearchResult] = []
        for result in results:
            if result.memory_type != MemoryType.EPISODIC:
                filtered.append(result)
                continue

            event_type = str(getattr(result.memory, "event_type", "")).strip()
            if event_type in {MemoryType.TASK_DIGEST.value, "archive_checkpoint"}:
                continue
            filtered.append(result)
        return filtered

    def _append_type_search_tasks(
        self,
        tasks: list[asyncio.Task[list[MemorySearchResult]]],
        *,
        memory_type: MemoryType,
        query: str,
        limit: int,
        include_raw: bool,
        config: MemoryConfig,
        query_vector: list[float] | None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> None:
        if memory_type == MemoryType.PROFILE and self._relational is not None:
            tasks.append(
                asyncio.create_task(
                    search_profile(query, limit, self._relational, namespaces=self._namespaces)
                )
            )
            return
        if memory_type == MemoryType.PROCEDURAL and self._relational is not None:
            tasks.append(
                asyncio.create_task(
                    search_procedural(query, limit, self._relational, namespaces=self._namespaces)
                )
            )
            return
        if memory_type == MemoryType.SEMANTIC and self._vector is not None and query_vector is not None:
            tasks.append(
                asyncio.create_task(
                    search_semantic(
                        query_vector,
                        limit,
                        self._vector,
                        config,
                        namespaces=self._namespaces,
                        since=since,
                        until=until,
                    )
                )
            )
            return
        if memory_type == MemoryType.EPISODIC and self._vector is not None and query_vector is not None:
            tasks.append(
                asyncio.create_task(
                    search_episodic(
                        query_vector,
                        limit,
                        self._vector,
                        config,
                        namespaces=self._namespaces,
                        since=since,
                        until=until,
                    )
                )
            )
            return
        if memory_type == MemoryType.CONVERSATION and self._vector is not None and query_vector is not None:
            self._append_conversation_tasks(
                tasks,
                query=query,
                limit=limit,
                include_raw=include_raw,
                config=config,
                query_vector=query_vector,
                since=since,
                until=until,
            )

    def _append_conversation_tasks(
        self,
        tasks: list[asyncio.Task[list[MemorySearchResult]]],
        *,
        query: str,
        limit: int,
        include_raw: bool,
        config: MemoryConfig,
        query_vector: list[float],
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> None:
        if self._config.retrieval.enable_two_pass_assistant_retrieval and is_assistant_reference_query(query):
            get_search_metrics().record_assistant_reference_query()
            use_dual = self._should_use_dual_channel(query)
            query_raw = query_vector if use_dual else None
            tasks.append(
                asyncio.create_task(
                    search_conversation_two_pass(
                        query_raw or query_vector,
                        query_vector,
                        query,
                        limit,
                        self._vector,
                        config,
                        namespaces=self._namespaces,
                        include_raw=include_raw,
                        since=since,
                        until=until,
                    )
                )
            )
            return

        use_dual = self._should_use_dual_channel(query)
        query_raw = query_vector if use_dual else None
        tasks.append(
            asyncio.create_task(
                search_conversation(
                    query_raw,
                    query_vector,
                    limit,
                    self._vector,
                    config,
                    namespaces=self._namespaces,
                    include_raw=include_raw,
                    since=since,
                    until=until,
                )
            )
        )
        if self._fts5_searcher is not None:
            tasks.append(asyncio.create_task(self._fts5_searcher(query, limit)))

    def _should_use_dual_channel(self, query: str) -> bool:
        if not self._config.retrieval.enable_adaptive_channel:
            return True
        return should_use_dual_channel(query, self._config.retrieval)

    def _rank_results(
        self,
        *,
        result_lists: list[list[MemorySearchResult]],
        query: str,
        limit: int,
        use_rrf: bool,
        config: MemoryConfig,
        query_context: object | None = None,
    ) -> list[MemorySearchResult]:
        retriever = MemoryRetriever(config.retrieval) if config != self._config else self._retriever
        if use_rrf and len(result_lists) > 1:
            return retriever.fuse(result_lists, limit=limit, query=query, query_context=query_context)
        merged = [memory for result_list in result_lists for memory in result_list]
        return retriever.rank(merged, limit=limit, query=query, query_context=query_context)

    def _strip_raw_exchange(self, results: list[MemorySearchResult]) -> list[MemorySearchResult]:
        return [
            (
                MemorySearchResult(
                    memory=result.memory.without_raw(), score=result.score, memory_type=result.memory_type
                )
                if isinstance(result.memory, ConversationMemory)
                else result
            )
            for result in results
        ]


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 3)
