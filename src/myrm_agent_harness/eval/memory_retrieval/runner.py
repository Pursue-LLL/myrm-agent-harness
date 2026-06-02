"""Memory Retrieval Eval Runner — orchestrates dataset-driven recall evaluation.

[INPUT]
- protocols::MemoryRetrievalAdapter (POS: pluggable memory backend)
- protocols::MemoryRetrievalEvalCase (POS: eval question definition)
- metrics (POS: IR scoring functions)

[OUTPUT]
- MemoryRetrievalEvalRunner: loads dataset, ingests, queries, scores, aggregates

[POS]
Orchestrates memory retrieval quality evaluation. Framework-only —
no business-layer imports. Business layer provides the adapter.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path

from myrm_agent_harness.eval.metrics import (
    hit_rate,
    latency_percentile,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

from .protocols import (
    MemoryRetrievalAdapter,
    MemoryRetrievalCaseResult,
    MemoryRetrievalCategorySummary,
    MemoryRetrievalEvalCase,
    MemoryRetrievalEvalSummary,
)

logger = logging.getLogger(__name__)

BUILTIN_DATASET_DIR = Path(__file__).parent / "datasets"


def load_eval_cases(path: str | Path | None = None) -> list[MemoryRetrievalEvalCase]:
    """Load eval cases from a JSON file.

    If path is None, loads the built-in coding_agent_life.json dataset.
    """
    if path is None:
        path = BUILTIN_DATASET_DIR / "coding_agent_life.json"
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    cases: list[MemoryRetrievalEvalCase] = []
    for entry in data.get("cases", []):
        cases.append(
            MemoryRetrievalEvalCase(
                id=entry["id"],
                category=entry["category"],
                query=entry["query"],
                gold_ids=entry["gold_ids"],
                language=entry.get("language", "en"),
                metadata=entry.get("metadata", {}),
            )
        )
    return cases


class MemoryRetrievalEvalRunner:
    """Executes memory retrieval eval cases against a MemoryRetrievalAdapter."""

    def __init__(self, adapter: MemoryRetrievalAdapter) -> None:
        self._adapter = adapter

    async def run(
        self,
        cases: list[MemoryRetrievalEvalCase],
        *,
        memories: list[dict[str, str]] | None = None,
    ) -> MemoryRetrievalEvalSummary:
        """Run full evaluation: ingest memories, query, score, aggregate.

        Args:
            cases: eval cases to run
            memories: list of dicts with keys {id, content, category?, language?}
                      If None, the runner expects memories are already ingested.
        """
        if memories:
            for mem in memories:
                await self._adapter.ingest(
                    memory_id=mem["id"],
                    content=mem["content"],
                    category=mem.get("category", ""),
                    language=mem.get("language", "en"),
                )

        results: list[MemoryRetrievalCaseResult] = []
        for case in cases:
            result = await self._run_case(case)
            results.append(result)

        summary = self._aggregate(results)

        if memories:
            try:
                await self._adapter.clear()
            except Exception:
                logger.warning("Adapter clear failed after eval run", exc_info=True)

        return summary

    async def _run_case(self, case: MemoryRetrievalEvalCase) -> MemoryRetrievalCaseResult:
        """Execute a single eval case."""
        gold = set(case.gold_ids)
        start = time.perf_counter()
        try:
            retrieved = await self._adapter.query(case.query, top_k=10)
        except Exception:
            logger.warning("Eval query failed for case %s", case.id, exc_info=True)
            retrieved = []
        elapsed_ms = (time.perf_counter() - start) * 1000

        return MemoryRetrievalCaseResult(
            case_id=case.id,
            category=case.category,
            retrieved_ids=retrieved,
            gold_ids=gold,
            recall_at_5=recall_at_k(retrieved, gold, 5),
            recall_at_10=recall_at_k(retrieved, gold, 10),
            ndcg_at_10=ndcg_at_k(retrieved, gold, 10),
            mrr_score=mrr(retrieved, gold),
            precision_at_5=precision_at_k(retrieved, gold, 5),
            hit_at_5=hit_rate(retrieved, gold, 5),
            latency_ms=elapsed_ms,
        )

    def _aggregate(self, results: list[MemoryRetrievalCaseResult]) -> MemoryRetrievalEvalSummary:
        """Aggregate per-case results into summary with category breakdown."""
        if not results:
            return MemoryRetrievalEvalSummary()

        n = len(results)
        latencies = [r.latency_ms for r in results]

        by_cat: dict[str, list[MemoryRetrievalCaseResult]] = defaultdict(list)
        for r in results:
            by_cat[r.category].append(r)

        cat_summaries: list[MemoryRetrievalCategorySummary] = []
        for cat, cat_results in sorted(by_cat.items()):
            cn = len(cat_results)
            cat_summaries.append(
                MemoryRetrievalCategorySummary(
                    category=cat,
                    count=cn,
                    recall_at_5=sum(r.recall_at_5 for r in cat_results) / cn,
                    recall_at_10=sum(r.recall_at_10 for r in cat_results) / cn,
                    ndcg_at_10=sum(r.ndcg_at_10 for r in cat_results) / cn,
                    mrr_score=sum(r.mrr_score for r in cat_results) / cn,
                    precision_at_5=sum(r.precision_at_5 for r in cat_results) / cn,
                    hit_at_5=sum(r.hit_at_5 for r in cat_results) / cn,
                )
            )

        return MemoryRetrievalEvalSummary(
            total_cases=n,
            recall_at_5=sum(r.recall_at_5 for r in results) / n,
            recall_at_10=sum(r.recall_at_10 for r in results) / n,
            ndcg_at_10=sum(r.ndcg_at_10 for r in results) / n,
            mrr_score=sum(r.mrr_score for r in results) / n,
            precision_at_5=sum(r.precision_at_5 for r in results) / n,
            hit_at_5=sum(r.hit_at_5 for r in results) / n,
            latency_p50_ms=latency_percentile(latencies, 50),
            latency_p95_ms=latency_percentile(latencies, 95),
            by_category=cat_summaries,
            case_results=results,
        )
