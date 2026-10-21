"""Cross-encoder rerank gate for the memory retrieval pipeline.

Applies a RerankerService (query-document cross-attention) to the fused
candidate list after graph enrichment, unifying the two incomparable score
systems — RRF-normalized fusion and graph sibling scoring — into one
relevance order before the output budget truncates.

Gate contract (fail-open; a disabled gate is a byte-identical no-op):
- No injected reranker or ``enable_cross_rerank`` off → pre-gate order.
- Candidate count at or below ``cross_rerank_min_candidates`` → pre-gate
  order: a network round-trip buys no ranking signal on a tiny list.
- Head candidates (top ``cross_rerank_top_n``) are scored through
  ``rerank_pairs`` in ``cross_rerank_batch_size`` batches; the tail keeps
  its pre-gate fused order.
- Timeout (pipeline deadline remainder, capped by ``cross_rerank_timeout``)
  or provider error degrades to the pre-gate order with GATHER_RERANK_*
  codes on the trace; the agent turn is never blocked.
- Applied scores replace ``MemorySearchResult.score`` on the head
  (max-normalized, floor-clamped at 0) so display order and relevance
  order agree; sorting is stable, so constant provider scores are no-ops.

[INPUT]
- memory config (RetrievalConfig cross_rerank_* fields)
- memory observability warning codes (GATHER_RERANK_TIMEOUT / GATHER_RERANK_FAILED)

[OUTPUT]
- RerankGateResult: post-gate order + gate metadata for the trace step
- apply_cross_rerank: async gate entry, fail-open on every path

[POS]
Sits between graph enrichment and raw-exchange stripping in the memory
search pipeline. Score semantics: the head carries cross-encoder
relevance, the tail keeps fused scores — order, not cross-boundary score
comparability, is the contract downstream budgeting relies on. The
RerankerService import is TYPE_CHECKING-only: the gate duck-types through
``rerank_pairs``, keeping the memory toolkit runtime-light.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Literal

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.observability import (
    GATHER_RERANK_FAILED,
    GATHER_RERANK_TIMEOUT,
)
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.retriever.reranker.base import RerankerService

logger = logging.getLogger(__name__)

RerankSkipReason = Literal[
    "no_reranker", "disabled", "too_few_candidates", "deadline_exhausted"
]
"""Why the gate did not apply (trace metadata; ``None`` when applied/degraded)."""


@dataclass(frozen=True, slots=True)
class RerankGateResult:
    """Outcome of one cross-encoder rerank gate application.

    Attributes:
        results: Post-gate order (the input list unchanged when not applied).
        applied: Cross-encoder scores actually reordered the head.
        degraded: Gate attempted but fell back to the pre-gate order.
        warning_codes: GATHER_RERANK_* codes to surface on the trace.
        skip_reason: Why the gate did not apply (``None`` when applied/degraded).
        reranked_count: Head candidates actually scored (0 when not applied).
        duration_ms: Gate wall-clock time in milliseconds.
    """

    results: list[MemorySearchResult]
    applied: bool
    degraded: bool
    warning_codes: tuple[str, ...]
    skip_reason: RerankSkipReason | None
    reranked_count: int
    duration_ms: float


def _skipped_result(
    results: list[MemorySearchResult], reason: RerankSkipReason, start: float
) -> RerankGateResult:
    """Assemble a not-applied gate outcome that keeps the pre-gate order."""
    return RerankGateResult(
        results=results,
        applied=False,
        degraded=False,
        warning_codes=(),
        skip_reason=reason,
        reranked_count=0,
        duration_ms=(perf_counter() - start) * 1000,
    )


def _degraded_result(
    results: list[MemorySearchResult], warning_codes: tuple[str, ...], start: float
) -> RerankGateResult:
    """Assemble a failed-open gate outcome that keeps the pre-gate order."""
    return RerankGateResult(
        results=results,
        applied=False,
        degraded=True,
        warning_codes=warning_codes,
        skip_reason=None,
        reranked_count=0,
        duration_ms=(perf_counter() - start) * 1000,
    )


def _warn_degradation(kind: str, detail: object) -> None:
    """Log a gate degradation; the pipeline records the metric and trace code."""
    logger.warning(
        "Cross-encoder rerank degraded (%s): %s; keeping fused order", kind, detail
    )


async def _score_in_batches(
    query: str,
    head: list[MemorySearchResult],
    *,
    reranker: RerankerService,
    batch_size: int,
) -> list[float]:
    """Score query-document pairs in provider-sized batches, sequentially for rate-limit safety."""
    scores: list[float] = []
    step = max(batch_size, 1)
    for offset in range(0, len(head), step):
        batch = head[offset : offset + step]
        pairs = [(query, result.memory.content) for result in batch]
        scores.extend(await reranker.rerank_pairs(pairs))
    return scores


def _reorder_head(head: list[MemorySearchResult], scores: list[float]) -> list[MemorySearchResult]:
    """Stable-sort the head by descending cross-encoder score.

    Max-normalized scores replace ``score`` (floor 0) so display agrees with
    order; a non-positive maximum (all-negative logits) floors the head at
    0.0 while the stable sort still preserves the fused order.
    """
    top = max(scores, default=0.0)
    order = sorted(range(len(head)), key=lambda i: (-scores[i], i))
    reordered: list[MemorySearchResult] = []
    for i in order:
        normalized = scores[i] / top if top > 0 else 0.0
        reordered.append(head[i].model_copy(update={"score": max(0.0, min(1.0, normalized))}))
    return reordered


async def apply_cross_rerank(
    results: list[MemorySearchResult],
    query: str,
    *,
    reranker: RerankerService | None,
    config: MemoryConfig,
    deadline: float,
) -> RerankGateResult:
    """Reorder the fused candidate head by cross-encoder relevance (fail-open).

    Args:
        results: Fused candidates in pre-gate order (descending fused score).
        query: Sanitized retrieval query.
        reranker: Injected reranker service; ``None`` disables the gate.
        config: Memory config (``retrieval.cross_rerank_*`` gate fields).
        deadline: Pipeline deadline in ``perf_counter`` seconds; the gate
            never spends more than the deadline remainder or its own timeout.

    Returns:
        The gate outcome; ``results`` is the post-gate order on every path.
    """
    start = perf_counter()
    if reranker is None:
        return _skipped_result(results, "no_reranker", start)
    retrieval = config.retrieval
    if not retrieval.enable_cross_rerank:
        return _skipped_result(results, "disabled", start)
    if len(results) <= retrieval.cross_rerank_min_candidates:
        return _skipped_result(results, "too_few_candidates", start)

    timeout = min(deadline - perf_counter(), retrieval.cross_rerank_timeout)
    if timeout <= 0:
        return _skipped_result(results, "deadline_exhausted", start)

    head_n = min(len(results), retrieval.cross_rerank_top_n)
    head = results[:head_n]
    tail = results[head_n:]
    try:
        scores = await asyncio.wait_for(
            _score_in_batches(
                query, head, reranker=reranker, batch_size=retrieval.cross_rerank_batch_size
            ),
            timeout=timeout,
        )
        if len(scores) != len(head):
            raise ValueError(f"reranker returned {len(scores)} scores for {len(head)} pairs")
    except TimeoutError:
        _warn_degradation("timeout", f"{timeout:.1f}s budget")
        return _degraded_result(results, (GATHER_RERANK_TIMEOUT,), start)
    except Exception as exc:
        _warn_degradation("error", exc)
        return _degraded_result(results, (GATHER_RERANK_FAILED,), start)

    return RerankGateResult(
        results=[*_reorder_head(head, scores), *tail],
        applied=True,
        degraded=False,
        warning_codes=(),
        skip_reason=None,
        reranked_count=len(head),
        duration_ms=(perf_counter() - start) * 1000,
    )
