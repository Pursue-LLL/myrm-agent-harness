"""Temporal Validity Governor enforcing explicit fact lifetimes and conflict suppression."""

import math
from collections.abc import Sequence
from datetime import UTC, datetime

from .models import (
    ConflictSuppressionReport,
    FactTemporalState,
    TemporalFactRecord,
)


class TemporalValidityGovernor:
    """Evaluates fact time intervals, performs temporal decay, and suppresses obsolete conflicting facts."""

    def __init__(self, suppression_penalty_ratio: float = 0.90) -> None:
        """Initialize governor.

        Args:
            suppression_penalty_ratio: Fraction by which obsolete fact confidence is penalized (0.0 to 1.0).
        """
        self._suppression_penalty_ratio = min(1.0, max(0.0, suppression_penalty_ratio))

    def is_valid_at(
        self,
        record: TemporalFactRecord,
        query_time: datetime | None = None,
    ) -> bool:
        """Verify whether the record is actively valid at the specified point in time."""
        if record.status != FactTemporalState.ACTIVE:
            return False

        now = self._ensure_utc(query_time or datetime.now(UTC))
        from_time = self._ensure_utc(record.valid_from)

        if now < from_time:
            return False

        if record.valid_to is not None:
            to_time = self._ensure_utc(record.valid_to)
            if now > to_time:
                return False

        return True

    def compute_temporal_decay(
        self,
        record: TemporalFactRecord,
        current_time: datetime | None = None,
        half_life_days: float = 30.0,
    ) -> float:
        """Calculate exponential time-decayed confidence score based on elapsed days since valid_from."""
        now = self._ensure_utc(current_time or datetime.now(UTC))
        from_time = self._ensure_utc(record.valid_from)

        delta_seconds = max(0.0, (now - from_time).total_seconds())
        delta_days = delta_seconds / 86400.0

        decay = math.pow(2.0, -delta_days / max(0.1, half_life_days))
        return max(0.0, min(1.0, record.confidence * decay))

    def suppress_conflicting_facts(
        self,
        candidates: Sequence[TemporalFactRecord],
        current_time: datetime | None = None,
    ) -> tuple[list[TemporalFactRecord], list[ConflictSuppressionReport]]:
        """Identify historical semantic collisions on the same (subject, predicate) and suppress obsolete facts.

        Returns:
            Tuple of (governed_records, reports).
        """
        # Group by canonical (subject, predicate) tuple
        grouped: dict[tuple[str, str], list[TemporalFactRecord]] = {}
        for r in candidates:
            key = (r.subject.strip().lower(), r.predicate.strip().lower())
            grouped.setdefault(key, []).append(r.model_copy(deep=True))

        governed_records: list[TemporalFactRecord] = []
        reports: list[ConflictSuppressionReport] = []

        for (subj, pred), group in grouped.items():
            if len(group) == 1:
                # Single fact on this attribute, no semantic collision
                governed_records.append(group[0])
                continue

            # Check if values diverge (i.e., genuine conflict exists)
            distinct_values = {g.value.strip().lower() for g in group}
            if len(distinct_values) <= 1:
                # Same value across multiple mentions, retain all
                governed_records.extend(group)
                continue

            # Sort candidate group by valid_from descending, then confidence descending
            group.sort(
                key=lambda item: (self._ensure_utc(item.valid_from), item.confidence),
                reverse=True,
            )

            prevailing = group[0]
            prevailing.status = FactTemporalState.ACTIVE
            suppressed_ids: list[str] = []

            for obsolete in group[1:]:
                obsolete.status = FactTemporalState.SUPERSEDED
                obsolete.superseded_by_id = prevailing.fact_id
                # Penalize confidence so that obsolete facts do not poison ranking
                obsolete.confidence = round(
                    obsolete.confidence * (1.0 - self._suppression_penalty_ratio),
                    3,
                )
                suppressed_ids.append(obsolete.fact_id)

            report = ConflictSuppressionReport(
                conflict_detected=True,
                subject=subj,
                predicate=pred,
                prevailing_fact_id=prevailing.fact_id,
                suppressed_fact_ids=suppressed_ids,
                suppression_penalty=self._suppression_penalty_ratio,
                rationale=(
                    f"Newer fact '{prevailing.fact_id}' (valid_from={prevailing.valid_from.isoformat()}) "
                    f"superseded {len(suppressed_ids)} historical claims for '{subj}.{pred}'."
                ),
            )

            reports.append(report)
            governed_records.extend(group)

        return governed_records, reports

    def _ensure_utc(self, dt: datetime) -> datetime:
        """Normalize naive or offset-aware datetime to UTC timezone."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
