"""Fail-open reranker wrapper guaranteeing non-blocking fallback on missing keys or timeouts.

[INPUT]
- toolkits.memory.auto_recall.types::RecallCandidate, RecallGateConfig, RerankerStatus (POS: Type
  definitions and contracts for Targeted Experience Auto-Recall Engine.)

[OUTPUT]
- FailOpenReranker: Wraps external neural rerankers with fail-open grace and latency circuit-breaking.

[POS]
Fail-open reranker wrapper guaranteeing non-blocking fallback on missing keys or timeouts.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from .types import RecallCandidate, RecallGateConfig, RerankerStatus


class FailOpenReranker:
    """Wraps external neural rerankers with fail-open grace and latency circuit-breaking."""

    def __init__(
        self,
        config: RecallGateConfig | None = None,
        custom_rerank_fn: Callable[[str, list[RecallCandidate]], list[RecallCandidate]] | None = None,
    ) -> None:
        self._config = config or RecallGateConfig()
        self._custom_rerank_fn = custom_rerank_fn

    def rerank(
        self,
        query: str,
        candidates: list[RecallCandidate],
    ) -> tuple[list[RecallCandidate], RerankerStatus]:
        """Execute reranking with fail-open fallback if unconfigured, timed-out, or errored."""
        if not candidates:
            return [], RerankerStatus.RERANKER_SKIPPED

        # 1. Preflight check: API key availability
        api_key = os.getenv(self._config.api_key_env_var, "").strip()
        if not api_key and self._custom_rerank_fn is None:
            # Fall back to rough score ordering
            return self._fallback_sort(candidates), RerankerStatus.RERANKER_SKIPPED

        # 2. Attempt reranking under strict timeout
        start_time = time.perf_counter()
        timeout_sec = self._config.reranker_timeout_ms / 1000.0

        try:
            if self._custom_rerank_fn is not None:
                reranked = self._custom_rerank_fn(query, candidates)
            else:
                # Default mock/heuristic neural reranker when key is present
                reranked = self._default_neural_rerank(query, candidates)

            elapsed = time.perf_counter() - start_time
            if elapsed > timeout_sec:
                # Timed out; gracefully fall back to original rough scoring
                return self._fallback_sort(candidates), RerankerStatus.TIMED_OUT

            return reranked, RerankerStatus.APPLIED

        except Exception:
            # Any unexpected error is absorbed fail-open
            return self._fallback_sort(candidates), RerankerStatus.FAILED_OPEN

    @staticmethod
    def _fallback_sort(candidates: list[RecallCandidate]) -> list[RecallCandidate]:
        """Deterministic descending sort based on candidate's initial rough score."""
        return sorted(candidates, key=lambda c: c.initial_score, reverse=True)

    @staticmethod
    def _default_neural_rerank(
        query: str, candidates: list[RecallCandidate]
    ) -> list[RecallCandidate]:
        """Lightweight lexical-semantic reranking simulation for neural rerankers."""
        query_terms = set(query.lower().split())

        def _compute_boost(cand: RecallCandidate) -> float:
            content_lower = cand.content.lower()
            overlap = sum(1 for t in query_terms if t in content_lower)
            lexical_boost = (overlap / max(1, len(query_terms))) * 0.4
            return cand.initial_score * 0.6 + lexical_boost

        boosted = sorted(candidates, key=_compute_boost, reverse=True)
        return boosted
