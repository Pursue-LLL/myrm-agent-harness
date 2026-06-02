"""Two-Pass Assistant Retrieval for assistant-reference queries (MemPalace enhancement).

Handles queries like "What did you recommend?" or "You told me X, remind me?".

Standard ConversationMemory search indexes user+assistant together, causing
semantic dilution when querying for assistant responses specifically.

Two-Pass strategy:
- Pass 1: Use summary_embedding to find top-N relevant sessions (user-centric)
- Pass 2: Use raw_embedding within top-N to pinpoint assistant responses
- Post-Pass: Apply ResultBooster to enhance precision

[I]
- user_id: str - User ID filter
- query_raw: list[float] - Raw embedding vector
- query_summary: list[float] - Summary embedding vector
- query: str - Original query text
- limit: int - Final result count
- vector: VectorStoreProtocol - Vector store backend
- config: MemoryConfig - Configuration
- include_raw: Whether to populate raw_exchange field

[O]
- list[MemorySearchResult] - Results with boosted scores, sorted by relevance

[P]
Implements Two-Pass retrieval + ResultBooster pipeline for assistant-reference
queries. Zero re-indexing cost due to MyrmAgent's dual-embedding design.

[INPUT]
- toolkits.vector.base::VectorStore (POS: Vector store abstraction layer. Defines backend-agnostic vector store interface and data models, inherited by all vector store implementations.)

[OUTPUT]
- search_conversation_two_pass: Two-Pass search for assistant-reference queries.

[POS]
Two-Pass Assistant Retrieval for assistant-reference queries (MemPalace enhancement).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.query_analyzer import analyze_query
from myrm_agent_harness.toolkits.memory.result_booster import boost_results
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult, MemoryType

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)


async def search_conversation_two_pass(
    query_raw: list[float],
    query_summary: list[float],
    query: str,
    limit: int,
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    *,
    namespaces: list[str] | None = None,
    include_raw: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[MemorySearchResult]:
    """Two-Pass search for assistant-reference queries.

    Pass 1: summary_embedding → top-N sessions (broad recall)
    Pass 2: raw_embedding within top-N → precise ranking
    Post-Pass: Apply ResultBooster (keyword/temporal/person_name/quoted_phrase boosts)

    Args:
        query_raw: Raw embedding vector
        query_summary: Summary embedding vector
        query: Original query text (for boosting)
        limit: Final result count
        vector: Vector store backend
        config: Memory configuration
        include_raw: Populate raw_exchange field
        since: Optional lower bound (inclusive) for created_at time filter.
        until: Optional upper bound (inclusive) for created_at time filter.

    Returns:
        Boosted and sorted search results
    """
    from myrm_agent_harness.toolkits.memory._internal.storage import doc_to_conversation
    from myrm_agent_harness.toolkits.memory.metrics import get_search_metrics
    from myrm_agent_harness.toolkits.vector.base import VectorStore

    start_ns = time.perf_counter_ns()

    collection = config.conversation_collection
    filters: dict[str, str | bool | list[str] | dict[str, list[str] | str]] = {
        "archived": False,
    }
    if namespaces:
        filters["namespaces"] = namespaces
    if since is not None or until is not None:
        time_range: dict[str, str] = {}
        if since is not None:
            time_range["gte"] = since.isoformat()
        if until is not None:
            time_range["lte"] = until.isoformat()
        filters["created_at"] = time_range
    score_threshold = config.similarity_threshold

    first_stage_limit = config.retrieval.two_pass_first_stage_limit

    # Pass 1: Use summary_embedding to find top-N sessions (user-centric)
    # This filters out irrelevant conversations before expensive Pass 2
    if isinstance(vector, VectorStore) and hasattr(vector, "search_multi_vector"):
        try:
            pass1_results = await vector.search_multi_vector(
                collection,
                named_vectors={"summary": query_summary},
                limit=first_stage_limit,
                filters=filters,
                score_threshold=score_threshold,
                fusion="rrf",  # Single vector, no actual fusion
            )
        except NotImplementedError:
            logger.debug(
                "Backend doesn't support search_multi_vector, fallback to regular search"
            )
            pass1_results = await vector.search(
                collection,
                query_summary,
                limit=first_stage_limit,
                filters=filters,
                score_threshold=score_threshold,
            )
    else:
        pass1_results = await vector.search(
            collection,
            query_summary,
            limit=first_stage_limit,
            filters=filters,
            score_threshold=score_threshold,
        )

    if not pass1_results:
        return []

    pass1_ids = {r.document.id for r in pass1_results}
    pass1_memory_results = [
        MemorySearchResult(
            memory=doc_to_conversation(
                r.document, include_raw=include_raw, config=config
            ),
            score=r.score,
            memory_type=MemoryType.CONVERSATION,
        )
        for r in pass1_results
    ]

    # Pass 2: Use raw_embedding within top-N sessions to pinpoint assistant responses
    # Filter by IDs from Pass 1 to search only within those sessions
    id_filters = filters.copy()
    id_filters["id"] = {"$in": list(pass1_ids)}

    try:
        if isinstance(vector, VectorStore) and hasattr(vector, "search_multi_vector"):
            try:
                pass2_results = await vector.search_multi_vector(
                    collection,
                    named_vectors={"raw": query_raw},
                    limit=limit,
                    filters=id_filters,
                    score_threshold=score_threshold,
                    fusion="rrf",  # Single vector, no actual fusion
                )
            except NotImplementedError:
                logger.debug(
                    "Backend doesn't support search_multi_vector for Pass 2, fallback"
                )
                pass2_results = await vector.search(
                    collection,
                    query_raw,
                    limit=limit,
                    filters=id_filters,
                    score_threshold=score_threshold,
                )
        else:
            pass2_results = await vector.search(
                collection,
                query_raw,
                limit=limit,
                filters=id_filters,
                score_threshold=score_threshold,
            )

        pass2_memory_results = [
            MemorySearchResult(
                memory=doc_to_conversation(
                    r.document, include_raw=include_raw, config=config
                ),
                score=r.score,
                memory_type=MemoryType.CONVERSATION,
            )
            for r in pass2_results
        ]

    except Exception as e:
        logger.warning(f"Two-Pass Pass 2 failed: {e}, fallback to Pass 1 results")
        pass2_memory_results = pass1_memory_results[:limit]

    # Post-Pass: Apply ResultBooster
    query_context = analyze_query(query)
    boosted_results = boost_results(
        pass2_memory_results, query, query_context, config.retrieval
    )

    elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
    get_search_metrics().record_two_pass_execution(elapsed_ms)

    return boosted_results
