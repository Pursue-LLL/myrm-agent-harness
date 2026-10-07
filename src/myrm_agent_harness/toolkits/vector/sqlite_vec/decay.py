"""Temporal decay scoring engine for agent vector memories.

[POS]
Provides mathematical temporal decay scoring and reranking capabilities to
diminish obsolete historical memories while preserving core durable norms.

[INPUT]
- math (exp, log)
- datetime (datetime, UTC)
- myrm_agent_harness.toolkits.vector.base (SearchResult, VectorDocument)
- myrm_agent_harness.toolkits.vector.sqlite_vec.models (DecayedSearchResult)

[OUTPUT]
- TemporalDecayScorer: Scorer class for computing exponential half-life decay
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.vector.base import SearchResult
from myrm_agent_harness.toolkits.vector.sqlite_vec.models import DecayedSearchResult


class TemporalDecayScorer:
    """Computes time-decayed similarity scores using exponential half-life curve.

    Formula:
        decay_raw = 2 ** (-delta_t / half_life)
        attenuated_decay = decay_raw ** (1.0 / max(1.0, importance_weight))
        decay_factor = floor_score + (1.0 - floor_score) * attenuated_decay
        final_score = raw_similarity * decay_factor
    """

    def __init__(
        self,
        default_half_life_seconds: float = 604800.0,
        floor_score: float = 0.2,
    ) -> None:
        """Initialize temporal decay scorer.

        Args:
            default_half_life_seconds: Default duration in seconds for score to halve (7 days).
            floor_score: Minimal retention floor in range [0.0, 1.0] to avoid complete erasure.
        """
        if default_half_life_seconds <= 0:
            msg = "Half-life duration must be strictly positive."
            raise ValueError(msg)
        if not 0.0 <= floor_score <= 1.0:
            msg = "Floor score must be within range [0.0, 1.0]."
            raise ValueError(msg)

        self.default_half_life_seconds: float = default_half_life_seconds
        self.floor_score: float = floor_score

    def compute_decay_factor(
        self,
        created_at: datetime,
        importance_weight: float = 1.0,
        half_life_seconds: float | None = None,
        now: datetime | None = None,
    ) -> float:
        """Calculate decay factor for a given timestamp and importance weight.

        Args:
            created_at: Creation timestamp of the document or record.
            importance_weight: Resistance multiplier (>= 1.0 reduces decay rate).
            half_life_seconds: Optional custom half life overriding default.
            now: Reference time (defaults to datetime.now(UTC)).

        Returns:
            Decay multiplier strictly in [floor_score, 1.0].
        """
        ref_now = now or datetime.now(UTC)
        if created_at.tzinfo is None:
            # Assume UTC if naive
            target_created = created_at.replace(tzinfo=UTC)
        else:
            target_created = created_at

        delta_seconds = max(0.0, (ref_now - target_created).total_seconds())
        effective_half_life = half_life_seconds or self.default_half_life_seconds

        # Compute raw exponential base-2 decay
        raw_exponent = -delta_seconds / effective_half_life
        raw_decay = math.pow(2.0, raw_exponent)

        # Attenuate decay rate with importance weight
        safe_weight = max(1.0, float(importance_weight))
        attenuated_decay = math.pow(raw_decay, 1.0 / safe_weight)

        # Scale into [floor_score, 1.0]
        factor = self.floor_score + (1.0 - self.floor_score) * attenuated_decay
        return min(1.0, max(self.floor_score, factor))

    def score_single(
        self,
        base_result: SearchResult,
        half_life_seconds: float | None = None,
        now: datetime | None = None,
    ) -> DecayedSearchResult:
        """Apply temporal decay to a single SearchResult.

        Extracts importance_weight from document metadata if available.
        """
        meta = base_result.document.metadata
        raw_weight = meta.get("importance_weight", 1.0)
        try:
            importance = float(raw_weight)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            importance = 1.0

        decay_factor = self.compute_decay_factor(
            created_at=base_result.document.created_at,
            importance_weight=importance,
            half_life_seconds=half_life_seconds,
            now=now,
        )
        decayed_score = base_result.score * decay_factor

        res = SearchResult(
            document=base_result.document,
            score=decayed_score,
        )
        return DecayedSearchResult.from_search_result(
            base_result=res,
            raw_sim=base_result.score,
            decay_fac=decay_factor,
        )

    def rerank(
        self,
        results: list[SearchResult],
        half_life_seconds: float | None = None,
        now: datetime | None = None,
        score_threshold: float | None = None,
    ) -> list[DecayedSearchResult]:
        """Rerank a batch of search results using temporal decay.

        Results are sorted descending by decayed_score.
        """
        decayed_items: list[DecayedSearchResult] = []
        for item in results:
            scored = self.score_single(
                base_result=item,
                half_life_seconds=half_life_seconds,
                now=now,
            )
            if score_threshold is not None and scored.decayed_score < score_threshold:
                continue
            decayed_items.append(scored)

        decayed_items.sort(key=lambda x: x.decayed_score, reverse=True)
        return decayed_items
