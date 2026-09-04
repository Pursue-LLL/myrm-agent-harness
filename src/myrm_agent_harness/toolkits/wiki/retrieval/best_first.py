"""Best-first retrieval convergence for wiki query.

[INPUT]
- ..core.claims_contract::WikiClaim, parse_claims_from_content, resolve_evidence_snapshot_status (POS: claim parse + snapshot tri-state)
- ..core.config::WikiQueryConfig (POS: query strategy knobs)
- ..core.structure::WikiStructure (POS: concept path resolution)
- .indexer::WikiIndexer (POS: weighted graph edge lookup)
- .tokenizer::extract_query_terms (POS: shared query term extraction)

[OUTPUT]
- RetrievalSeed, score_claim_overlap, converge_retrieval_candidates

[POS]
Budgeted priority-queue convergence over index/FTS/sidecar/keyword seeds plus weighted
graph expansion. Supports raw_claim rerank via frontmatter claim overlap boosts and claim-health
multipliers (supported/contested/stale evidence).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..core.claims_contract import (
    WikiClaim,
    parse_claims_from_content,
    resolve_evidence_snapshot_status,
)
from ..core.fact_trust_contract import (
    DEFAULT_FACT_TRUST_POLICY,
    FactTrustPolicy,
    resolve_fact_status,
)
from .tokenizer import extract_query_terms

if TYPE_CHECKING:
    from ..core.config import WikiQueryConfig
    from ..core.structure import WikiStructure
    from .indexer import WikiIndexer

SOURCE_TIER_BOOST: dict[str, float] = {
    "index": 100.0,
    "fts": 70.0,
    "sidecar": 55.0,
    "keyword": 35.0,
    "graph": 15.0,
}
RAW_CLAIM_TIER_BOOST = 50.0
NON_CLAIM_DEMOTION = 0.5
CLAIM_STATUS_MULTIPLIER: dict[str, float] = {
    "supported": 1.15,
    "contested": 0.7,
    "unsupported": 0.5,
    "unknown": 0.85,
}
STALE_EVIDENCE_MULTIPLIER = 0.6
DEFAULT_CLAIM_CONFIDENCE = 0.5


@dataclass(frozen=True, slots=True)
class RetrievalSeed:
    """Single retrieval candidate before best-first convergence."""

    concept_name: str
    score: float
    source: str


def _claim_health_multiplier(
    claim: WikiClaim,
    *,
    structure: WikiStructure | None,
) -> float:
    multiplier = CLAIM_STATUS_MULTIPLIER.get(claim.status, 1.0)
    if structure is None or not claim.evidence:
        return multiplier
    if any(
        resolve_evidence_snapshot_status(
            evidence.path, evidence.content_sha256, structure
        )
        == "stale"
        for evidence in claim.evidence
    ):
        multiplier *= STALE_EVIDENCE_MULTIPLIER
    return multiplier


def _claim_confidence_factor(claim: WikiClaim) -> float:
    confidence = claim.confidence
    if confidence <= 0.0 or confidence == DEFAULT_CLAIM_CONFIDENCE:
        return 1.0
    return 1.0 + 0.2 * min(1.0, confidence)


def score_claim_overlap(
    content: str,
    query_terms: frozenset[str],
    *,
    structure: WikiStructure | None = None,
) -> float:
    """Return best normalized query/claim term overlap score for a concept body."""
    if not query_terms:
        return 0.0
    best = 0.0
    for claim in parse_claims_from_content(content):
        claim_terms = extract_query_terms(claim.text)
        overlap = len(query_terms & claim_terms)
        if overlap <= 0:
            continue
        score = overlap / max(len(query_terms), 1)
        score *= _claim_health_multiplier(claim, structure=structure)
        score *= _claim_confidence_factor(claim)
        best = max(best, score)
    return best


def _apply_claim_mode_adjustment(
    *,
    query_config: WikiQueryConfig,
    claim_overlap: float,
    base_score: float,
) -> float:
    if claim_overlap <= 0:
        return base_score * (
            NON_CLAIM_DEMOTION if query_config.query_mode == "raw_claim" else 1.0
        )

    boosted = base_score + claim_overlap * query_config.raw_claim_boost
    if query_config.query_mode == "raw_claim":
        boosted += RAW_CLAIM_TIER_BOOST
    return boosted


def _claim_overlap_for_concept(
    *,
    structure: WikiStructure,
    concept_name: str,
    query_terms: frozenset[str],
    cache: dict[str, float],
    trust_policy: FactTrustPolicy = DEFAULT_FACT_TRUST_POLICY,
) -> float:
    if concept_name in cache:
        return cache[concept_name]
    path = structure.resolve_concept_file_path(concept_name)
    if not path or not path.exists():
        cache[concept_name] = 0.0
        return 0.0
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        cache[concept_name] = 0.0
        return 0.0
    overlap = score_claim_overlap(content, query_terms, structure=structure)
    status = resolve_fact_status(content, file_path=path)
    overlap *= trust_policy.get_multiplier(status)
    cache[concept_name] = overlap
    return overlap


def converge_retrieval_candidates(
    *,
    query: str,
    query_config: WikiQueryConfig,
    structure: WikiStructure,
    indexer: WikiIndexer,
    seeds: list[RetrievalSeed],
    max_results: int,
    valid_names: frozenset[str] | None = None,
) -> list[str]:
    """Budgeted best-first convergence over seeds plus weighted graph expansion."""
    if max_results <= 0 or not seeds:
        return []

    query_terms = frozenset(extract_query_terms(query))
    claim_overlap_cache: dict[str, float] = {}
    heap: list[tuple[float, int, str]] = []
    counter = 0
    queued: set[str] = set()

    def enqueue(name: str, score: float) -> None:
        nonlocal counter
        normalized = name.strip().replace("\\", "/")
        if not normalized or normalized in queued:
            return
        if valid_names is not None and normalized not in valid_names:
            return
        path = structure.resolve_concept_file_path(normalized)
        if not path or not path.exists():
            return
        overlap = _claim_overlap_for_concept(
            structure=structure,
            concept_name=normalized,
            query_terms=query_terms,
            cache=claim_overlap_cache,
        )
        adjusted = _apply_claim_mode_adjustment(
            query_config=query_config,
            claim_overlap=overlap,
            base_score=score,
        )
        queued.add(normalized)
        heapq.heappush(heap, (-adjusted, counter, normalized))
        counter += 1

    for seed in seeds:
        tier = SOURCE_TIER_BOOST.get(seed.source, 0.0)
        enqueue(seed.concept_name, seed.score + tier)

    results: list[str] = []
    seen: set[str] = set()
    expansions = 0
    max_expansions = max(0, query_config.best_first_max_expansions)

    while heap and len(results) < max_results and expansions <= max_expansions:
        neg_score, _, name = heapq.heappop(heap)
        if name in seen:
            continue
        seen.add(name)
        results.append(name)

        parent_score = -neg_score
        decay = query_config.best_first_graph_decay
        for target, weight in indexer.get_outgoing_edges(name):
            if target in seen:
                continue
            child_score = parent_score * decay + float(weight)
            enqueue(target, child_score)
            expansions += 1

    return results
