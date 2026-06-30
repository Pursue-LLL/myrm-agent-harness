"""Graph enrichment helpers for memory maintenance search.

[INPUT]
- maintenance_claim_support::search_claim_graph (POS: claim graph search)
- memory.protocols.graph::GraphStoreProtocol (POS: graph store protocol)

[OUTPUT]
- enrich_with_graph(): expand search results with graph siblings and claims

[POS]
Graph enrichment for memory search. Expands results with claim recall and graph sibling scoring.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory._internal.storage import doc_to_episodic
from myrm_agent_harness.toolkits.memory._internal.maintenance_claim_support import (
    _QUERY_TOKEN_PATTERN,
    search_claim_graph as _search_claim_graph,
)
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemorySearchResult, MemoryType
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphStoreProtocol
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)

def _content_hash(content: str) -> str:
    """Calculate normalized MD5 hash for content deduplication.

    Normalizes whitespace and case before hashing so that
    'Hello' and ' hello ' are treated as duplicates.
    """
    normalized = content.strip().lower()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _freshness_from_age_days(age_days: int) -> str:
    """Convert age in days to freshness bucket."""
    if age_days <= 7:
        return "fresh"
    if age_days <= 30:
        return "aging"
    return "stale"


def _score_sibling_node(
    query_tokens: set[str],
    content: str,
    *,
    depth: int,
    distance_decay: float,
    importance: float,
    created_at: datetime | None,
    current_channel_id: str | None,
    channel_id: str | None,
    now: datetime | None = None,
) -> float:
    """Unified scoring for graph sibling nodes (same formula as Claim Graph).

    Combines: token overlap + distance decay + freshness + importance + channel affinity.
    """
    if not query_tokens:
        return 0.0

    now = now or datetime.now(UTC)
    content_tokens = set(_QUERY_TOKEN_PATTERN.findall(content.lower()))
    overlap = len(query_tokens & content_tokens)
    if overlap == 0:
        return 0.0

    # Token overlap base (mirrors _score_claim_node formula)
    score = min(0.55 + overlap * 0.08, 0.88)

    # Distance decay: depth=1 → 1.0x, depth=2 → decay factor
    score *= distance_decay ** (depth - 1)

    # Freshness boost
    if created_at:
        age_days = max(0, (now - created_at).days)
        freshness = _freshness_from_age_days(age_days)
        if freshness == "fresh":
            score += 0.08
        elif freshness == "aging":
            score += 0.04

    # Importance modulation (episodic memories have importance 0-1)
    score *= 0.7 + 0.3 * max(0.0, min(importance, 1.0))

    # Channel affinity boost
    if current_channel_id and channel_id and current_channel_id == channel_id:
        score += 0.06

    return max(0.0, min(score, 0.95))


async def enrich_with_graph(
    results: list[MemorySearchResult],
    query: str,
    limit: int,
    graph: GraphStoreProtocol,
    vector: VectorStoreProtocol | None,
    config: MemoryConfig,
    *,
    current_channel_id: str | None = None,
    namespaces: list[str] | None = None,
) -> list[MemorySearchResult]:
    """Expand results with graph siblings and Claim Graph recall.

    Optimization features:
    - Unified scoring: token overlap + distance decay + freshness + importance + channel affinity
    - Distance-based scoring: depth=1 gets base score, depth=2 gets base*decay
    - Configurable sibling limit via config.graph_sibling_limit
    - Content-level dedup using MD5 hash
    - Multi-hop traversal via get_related_nodes_with_depth
    """
    existing_ids = {r.id for r in results}
    existing_hashes: set[str] = set()
    claim_results: list[MemorySearchResult] = []
    try:
        claim_results = await _search_claim_graph(
            graph,
            query=query,
            current_channel_id=current_channel_id,
            namespaces=namespaces,
            limit=limit,
        )
    except Exception as e:
        logger.warning("Claim graph search failed (non-fatal): %s", e)

    for claim_result in claim_results:
        if claim_result.id in existing_ids:
            continue
        results.append(claim_result)
        existing_ids.add(claim_result.id)

    episodic_hits = [r for r in results if isinstance(r.memory, EpisodicMemory)]
    if not episodic_hits:
        return results[:limit]

    if vector is None:
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

    # Multi-hop traversal with depth tracking (parallel)
    related_with_depth: dict[str, int] = {}
    sibling_limit = config.graph_sibling_limit
    max_depth = config.graph_max_depth

    async def _fetch_siblings(memory_id: str) -> list[tuple[str, int]]:
        try:
            return await graph.get_related_nodes_with_depth(memory_id, "MENTIONS", max_depth=max_depth)
        except Exception:
            try:
                return [(mid, 1) for mid in await graph.get_related_nodes(memory_id, "MENTIONS")]
            except Exception:
                return []

    sibling_lists = await asyncio.gather(*[_fetch_siblings(r.memory.id) for r in episodic_hits])
    for siblings in sibling_lists:
        for mid, depth in siblings:
            if mid not in existing_ids and mid not in related_with_depth:
                related_with_depth[mid] = depth

    if not related_with_depth:
        return results

    # Sort by depth (prefer direct siblings) and apply limit
    sorted_ids = sorted(related_with_depth.keys(), key=lambda x: related_with_depth[x])
    limited_ids = sorted_ids[:sibling_limit]

    try:
        docs = await vector.get(config.episodic_collection, limited_ids)
        query_tokens = set(_QUERY_TOKEN_PATTERN.findall(query.lower()))
        now = datetime.now(UTC)
        for doc in docs:
            if doc.metadata.get("status") in (
                "archived",
                "disabled",
            ) or doc.metadata.get("archived"):
                continue

            # Content-level dedup
            content_hash = _content_hash(doc.content)
            if content_hash in existing_hashes:
                continue
            existing_hashes.add(content_hash)

            mem = doc_to_episodic(doc)
            depth = related_with_depth.get(doc.id, 1)

            # Unified scoring (same formula as Claim Graph)
            doc_channel_id = str(doc.metadata.get("channel_id", "")) or None
            latest_at = mem.updated_at or mem.created_at
            score = _score_sibling_node(
                query_tokens=query_tokens,
                content=doc.content,
                depth=depth,
                distance_decay=config.graph_distance_decay,
                importance=mem.importance,
                created_at=latest_at,
                current_channel_id=current_channel_id,
                channel_id=doc_channel_id,
                now=now,
            )

            results.append(
                MemorySearchResult(
                    memory=mem,
                    score=score,
                    memory_type=MemoryType.EPISODIC,
                )
            )
    except Exception as e:
        logger.warning("Graph enrichment failed (non-fatal): %s", e)
    results.sort(key=lambda item: item.score, reverse=True)
    return results[:limit]
