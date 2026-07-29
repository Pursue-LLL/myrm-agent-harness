"""Deterministic wiki retrieval benchmark — CI gate for hybrid search regressions.

[INPUT]
..core.config::WikiConfig (POS: indexer configuration)
..core.structure::WikiStructure (POS: vault layout)
..retrieval.indexer::WikiIndexer (POS: FTS5 hybrid search)

[OUTPUT]
WikiRecallBenchmarkCase/Result/Summary, run_wiki_recall_benchmark, summarize_wiki_recall_benchmark

[POS]
Offline retrieval quality probe. Measures whether expected concepts appear in top-k
search results — no LLM, no agent tools, no user vault mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

BENCHMARK_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class WikiRecallBenchmarkCase:
    """One query with an expected indexed concept name."""

    case_id: str
    query: str
    expected_concept_name: str
    top_k: int = 5


@dataclass(frozen=True, slots=True)
class WikiRecallBenchmarkResult:
    """Result for one retrieval benchmark case."""

    case_id: str
    expected_found: bool
    best_rank: int | None
    top_k: int
    latency_ms: float


@dataclass(frozen=True, slots=True)
class WikiRecallBenchmarkSummary:
    """Aggregate retrieval benchmark metrics suitable for CI gates."""

    schema_version: int
    case_count: int
    passed_count: int
    recall_at_k: float
    latency_p50_ms: float
    latency_p95_ms: float

    @property
    def status(self) -> str:
        if self.case_count == 0:
            return "missing"
        if self.recall_at_k >= 0.9:
            return "ready"
        if self.recall_at_k >= 0.7:
            return "warning"
        return "critical"


def _normalize_concept_name(name: str) -> str:
    return name.strip().lower().replace("\\", "/")


def _match_rank(hits: list[tuple[str, float]], expected_concept_name: str, top_k: int) -> int | None:
    expected = _normalize_concept_name(expected_concept_name)
    for index, (concept_name, _score) in enumerate(hits[:top_k], start=1):
        if _normalize_concept_name(concept_name) == expected:
            return index
    return None


async def run_wiki_recall_benchmark(
    structure: WikiStructure,
    config: WikiConfig,
    cases: list[WikiRecallBenchmarkCase],
) -> list[WikiRecallBenchmarkResult]:
    """Run deterministic retrieval checks against an indexed vault."""
    indexer = WikiIndexer(structure, config)
    results: list[WikiRecallBenchmarkResult] = []
    for case in cases:
        started = perf_counter()
        hits = await indexer.search(case.query, limit=case.top_k)
        latency_ms = (perf_counter() - started) * 1000.0
        best_rank = _match_rank(hits, case.expected_concept_name, case.top_k)
        results.append(
            WikiRecallBenchmarkResult(
                case_id=case.case_id,
                expected_found=best_rank is not None,
                best_rank=best_rank,
                top_k=case.top_k,
                latency_ms=latency_ms,
            )
        )
    return results


def summarize_wiki_recall_benchmark(results: list[WikiRecallBenchmarkResult]) -> WikiRecallBenchmarkSummary:
    """Summarize benchmark results without inspecting article bodies."""
    if not results:
        return WikiRecallBenchmarkSummary(
            schema_version=BENCHMARK_SCHEMA_VERSION,
            case_count=0,
            passed_count=0,
            recall_at_k=0.0,
            latency_p50_ms=0.0,
            latency_p95_ms=0.0,
        )

    case_count = len(results)
    passed_count = sum(1 for result in results if result.expected_found)
    latencies = sorted(result.latency_ms for result in results)
    p50_index = max(0, (case_count + 1) // 2 - 1)
    p95_index = max(0, int(case_count * 0.95) - 1)
    return WikiRecallBenchmarkSummary(
        schema_version=BENCHMARK_SCHEMA_VERSION,
        case_count=case_count,
        passed_count=passed_count,
        recall_at_k=passed_count / case_count,
        latency_p50_ms=latencies[p50_index],
        latency_p95_ms=latencies[p95_index],
    )
