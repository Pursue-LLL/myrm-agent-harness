"""Cross-encoder rerank gate tests.

Covers the full gate contract: skip paths (no reranker / disabled / too few
candidates / deadline exhausted), applied reorder with score normalization,
tail order preservation, batching, stable-sort no-ops, and both degradation
paths (timeout, provider error, score-count mismatch).
"""

import asyncio
from dataclasses import replace
from time import perf_counter

import pytest

from myrm_agent_harness.toolkits.memory._internal.rerank_gate import apply_cross_rerank
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.observability import (
    GATHER_RERANK_FAILED,
    GATHER_RERANK_TIMEOUT,
)
from myrm_agent_harness.toolkits.memory.types import (
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)
from myrm_agent_harness.toolkits.retriever.reranker.base import RerankerService, RerankResult


def _fresh_deadline() -> float:
    """Per-call deadline: a module-level constant would expire under long runs."""
    return perf_counter() + 30.0


class StubReranker(RerankerService):
    """Scripted reranker: fixed pair scores, optional error or delay. No network."""

    def __init__(
        self,
        scores: list[float] | None = None,
        *,
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.scores = scores or []
        self.error = error
        self.delay = delay
        self.pairs_batches: list[list[tuple[str, str]]] = []

    async def rerank(self, query: str, documents: list[str], top_k: int | None = None) -> list[RerankResult]:
        # The gate must only enter through rerank_pairs; rerank is a guard.
        raise AssertionError("gate must call rerank_pairs, not rerank")

    async def rerank_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        self.pairs_batches.append(list(pairs))
        return list(self.scores)


def _config(**retrieval_overrides: object) -> MemoryConfig:
    base = MemoryConfig(embedding_model="test-model")
    return replace(base, retrieval=replace(base.retrieval, **retrieval_overrides))


def _result(rid: str, content: str, score: float = 0.9) -> MemorySearchResult:
    return MemorySearchResult(
        memory=SemanticMemory(id=rid, content=content, user_id="user"),
        score=score,
        memory_type=MemoryType.SEMANTIC,
    )


async def test_skip_without_reranker() -> None:
    results = [_result("a", "alpha"), _result("b", "beta")]
    outcome = await apply_cross_rerank(
        results, "query", reranker=None, config=_config(), deadline=_fresh_deadline()
    )
    assert outcome.results is results
    assert not outcome.applied
    assert not outcome.degraded
    assert outcome.skip_reason == "no_reranker"
    assert outcome.reranked_count == 0


async def test_skip_when_disabled_by_config() -> None:
    reranker = StubReranker(scores=[0.9, 0.1])
    results = [_result("a", "alpha"), _result("b", "beta")]
    outcome = await apply_cross_rerank(
        results,
        "query",
        reranker=reranker,
        config=_config(enable_cross_rerank=False),
        deadline=_fresh_deadline(),
    )
    assert outcome.results is results
    assert outcome.skip_reason == "disabled"
    assert reranker.pairs_batches == []


async def test_skip_when_too_few_candidates() -> None:
    reranker = StubReranker(scores=[0.9, 0.1])
    results = [_result("a", "alpha"), _result("b", "beta")]
    outcome = await apply_cross_rerank(
        results,
        "query",
        reranker=reranker,
        config=_config(),  # min_candidates=3, only 2 supplied
        deadline=_fresh_deadline(),
    )
    assert outcome.results is results
    assert outcome.skip_reason == "too_few_candidates"


async def test_skip_when_deadline_exhausted() -> None:
    reranker = StubReranker(scores=[0.9] * 4)
    results = [_result(i, f"doc {i}") for i in "abcd"]
    outcome = await apply_cross_rerank(
        results, "query", reranker=reranker, config=_config(), deadline=perf_counter() - 1.0
    )
    assert outcome.results is results
    assert outcome.skip_reason == "deadline_exhausted"
    assert reranker.pairs_batches == []


async def test_applied_reorders_head_and_normalizes_scores() -> None:
    # Fused order a,b,c,d; cross-encoder says c > d > a > b.
    reranker = StubReranker(scores=[0.2, 0.1, 0.8, 0.4])
    results = [_result(rid, f"doc {rid}") for rid in "abcd"]
    outcome = await apply_cross_rerank(
        results, "query", reranker=reranker, config=_config(), deadline=_fresh_deadline()
    )
    assert outcome.applied
    assert not outcome.degraded
    assert outcome.reranked_count == 4
    assert [r.memory.id for r in outcome.results] == ["c", "d", "a", "b"]
    # Max-normalized: top gets 1.0, others scale down and stay in [0, 1].
    assert outcome.results[0].score == pytest.approx(1.0)
    assert outcome.results[1].score == pytest.approx(0.5)
    assert outcome.results[2].score == pytest.approx(0.25)
    assert outcome.results[3].score == pytest.approx(0.125)
    # The provider saw (query, content) pairs in the fused order.
    assert reranker.pairs_batches[0][0] == ("query", "doc a")


async def test_tail_keeps_fused_order() -> None:
    # top_n=2: only a,b are reranked; c,d keep the fused order after them.
    reranker = StubReranker(scores=[0.1, 0.9])
    results = [_result(rid, f"doc {rid}") for rid in "abcd"]
    outcome = await apply_cross_rerank(
        results,
        "query",
        reranker=reranker,
        config=_config(cross_rerank_top_n=2),
        deadline=_fresh_deadline(),
    )
    assert outcome.applied
    assert outcome.reranked_count == 2
    assert [r.memory.id for r in outcome.results] == ["b", "a", "c", "d"]
    # Tail keeps fused scores; head carries cross-encoder scores.
    assert outcome.results[2].score == pytest.approx(0.9)


async def test_batches_follow_configured_size() -> None:
    reranker = StubReranker(scores=[0.1, 0.9, 0.5, 0.7])
    results = [_result(i, f"doc {i}") for i in "abcd"]
    await apply_cross_rerank(
        results,
        "query",
        reranker=reranker,
        config=_config(cross_rerank_batch_size=2),
        deadline=_fresh_deadline(),
    )
    assert [len(batch) for batch in reranker.pairs_batches] == [2, 2]


async def test_constant_scores_are_a_stable_noop() -> None:
    reranker = StubReranker(scores=[0.5, 0.5, 0.5, 0.5])
    results = [_result(rid, f"doc {rid}") for rid in "abcd"]
    outcome = await apply_cross_rerank(
        results, "query", reranker=reranker, config=_config(), deadline=_fresh_deadline()
    )
    assert outcome.applied
    assert [r.memory.id for r in outcome.results] == ["a", "b", "c", "d"]
    assert all(r.score == pytest.approx(1.0) for r in outcome.results)


async def test_negative_scores_floor_to_zero_but_keep_order() -> None:
    # All-negative logits: max is negative, so scores floor at 0.0 while the
    # stable sort preserves the fused order.
    reranker = StubReranker(scores=[-0.2, -0.9, -0.5, -0.7])
    results = [_result(rid, f"doc {rid}") for rid in "abcd"]
    outcome = await apply_cross_rerank(
        results, "query", reranker=reranker, config=_config(), deadline=_fresh_deadline()
    )
    assert outcome.applied
    # Negative logits still rank: -0.2 > -0.5 > -0.7 > -0.9.
    assert [r.memory.id for r in outcome.results] == ["a", "c", "d", "b"]
    assert all(r.score == 0.0 for r in outcome.results)


async def test_timeout_degrades_to_fused_order() -> None:
    reranker = StubReranker(delay=5.0)
    results = [_result(rid, f"doc {rid}") for rid in "abcd"]
    outcome = await apply_cross_rerank(
        results,
        "query",
        reranker=reranker,
        config=_config(cross_rerank_timeout=0.05),
        deadline=_fresh_deadline(),
    )
    assert outcome.results is results
    assert outcome.degraded
    assert not outcome.applied
    assert outcome.warning_codes == (GATHER_RERANK_TIMEOUT,)


async def test_provider_error_degrades_to_fused_order() -> None:
    reranker = StubReranker(error=RuntimeError("provider down"))
    results = [_result(rid, f"doc {rid}") for rid in "abcd"]
    outcome = await apply_cross_rerank(
        results, "query", reranker=reranker, config=_config(), deadline=_fresh_deadline()
    )
    assert outcome.results is results
    assert outcome.degraded
    assert outcome.warning_codes == (GATHER_RERANK_FAILED,)


async def test_score_count_mismatch_degrades() -> None:
    # Provider returns 2 scores for 4 pairs: contract violation → fail-open.
    reranker = StubReranker(scores=[0.5, 0.5])
    results = [_result(rid, f"doc {rid}") for rid in "abcd"]
    outcome = await apply_cross_rerank(
        results, "query", reranker=reranker, config=_config(), deadline=_fresh_deadline()
    )
    assert outcome.results is results
    assert outcome.degraded
    assert outcome.warning_codes == (GATHER_RERANK_FAILED,)
