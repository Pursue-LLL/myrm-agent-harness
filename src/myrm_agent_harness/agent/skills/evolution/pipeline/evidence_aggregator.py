"""Evidence Aggregator for Skill Evolution.

Queries execution_analyses and groups them by skill_id, separating
success and failure cases. Extracts common error patterns to give the
evolution engine a full-picture view for smarter repair decisions.

[INPUT]
- agent.skills.evolution.db.store::SkillStore (POS: SQLite persistence for skill evolution system.)

[OUTPUT]
- EvidenceAggregator: Aggregates execution evidence by skill for evidence-driven evolution.

[POS]
Evidence Aggregator for Skill Evolution.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime

from myrm_agent_harness.agent.skills.evolution.core.types import (
    ExecutionAnalysis,
    SkillEvidenceGroup,
)
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore

logger = logging.getLogger(__name__)

__all__ = ["EvidenceAggregator"]


class EvidenceAggregator:
    """Aggregates execution evidence by skill for evidence-driven evolution.

    Reads from execution_analyses table, groups by skill_id, and returns
    SkillEvidenceGroup objects containing both success and failure cases.

    Dual-window design:
    - Primary window (default 7 days): Recent evidence for immediate decisions
    - Trend window (default 30 days): Longer lookback for slow-degradation detection
    """

    TREND_WINDOW_DAYS: int = 30

    def __init__(self, store: SkillStore, lookback_days: int = 7) -> None:
        self._store = store
        self._lookback_days = lookback_days

    def aggregate(self) -> list[SkillEvidenceGroup]:
        """Aggregate recent execution analyses into evidence groups.

        Returns:
            List of SkillEvidenceGroup, one per skill that has recent activity.
        """
        raw_groups = self._store.get_recent_analyses_grouped(days=self._lookback_days)

        # Fetch 30-day trend failure counts (single query, minimal cost)
        trend_failures = self._store.get_trend_failure_counts(days=self.TREND_WINDOW_DAYS)

        if not raw_groups and not trend_failures:
            logger.debug("No recent execution analyses to aggregate")
            return []

        evidence_groups: list[SkillEvidenceGroup] = []
        processed_skill_ids: set[str] = set()

        for skill_id, rows in raw_groups.items():
            skill_record = self._store.get_skill(skill_id)
            if not skill_record or not skill_record.is_active:
                continue

            success_cases: list[ExecutionAnalysis] = []
            failure_cases: list[ExecutionAnalysis] = []
            error_messages: list[str] = []

            for row in rows:
                analysis = ExecutionAnalysis(
                    skill_id=str(row["skill_id"]),
                    task_id=str(row["task_id"]),
                    success=bool(row["success"]),
                    error_message=str(row.get("error_message", "")),
                    root_cause=str(row.get("root_cause", "")),
                    suggested_fix=str(row.get("suggested_fix", "")),
                    task_context=str(row.get("task_context", "")),
                    analyzed_at=datetime.fromisoformat(str(row["analyzed_at"])),
                )

                if analysis.success:
                    success_cases.append(analysis)
                else:
                    failure_cases.append(analysis)
                    if analysis.error_message:
                        error_messages.append(analysis.error_message)

            common_errors = self._extract_common_error_patterns(error_messages)
            confidence = self._compute_confidence(failure_cases, common_errors)

            group = SkillEvidenceGroup(
                skill_id=skill_id,
                skill_name=skill_record.name,
                success_cases=success_cases,
                failure_cases=failure_cases,
                metrics_snapshot=skill_record.metrics,
                common_error_patterns=common_errors,
                trend_failure_count=trend_failures.get(skill_id, 0),
                confidence=confidence,
            )
            evidence_groups.append(group)
            processed_skill_ids.add(skill_id)

        # Trend-only skills: not active in 7-day window but have 30-day failures
        for skill_id, fail_count in trend_failures.items():
            if skill_id in processed_skill_ids:
                continue
            if fail_count < 3:
                continue
            skill_record = self._store.get_skill(skill_id)
            if not skill_record or not skill_record.is_active:
                continue

            group = SkillEvidenceGroup(
                skill_id=skill_id,
                skill_name=skill_record.name,
                trend_failure_count=fail_count,
                confidence=0.5,
            )
            evidence_groups.append(group)

        logger.info(
            "Aggregated evidence for %d skills (%d with sufficient evidence)",
            len(evidence_groups),
            sum(1 for g in evidence_groups if g.has_sufficient_evidence()),
        )

        return evidence_groups

    def _compute_confidence(
        self, failure_cases: list[ExecutionAnalysis], common_errors: list[str]
    ) -> float:
        """Compute evidence confidence based on error pattern consistency.

        High confidence (>0.7): Failures share a common error pattern (likely fixable).
        Low confidence (<0.4): Scattered random errors (likely environmental/transient).
        """
        if not failure_cases:
            return 1.0

        total_failures = len(failure_cases)
        if total_failures == 1:
            return 0.6

        # If top error pattern accounts for >50% of failures, high confidence
        if common_errors:
            top_pattern = common_errors[0]
            matching = sum(
                1 for f in failure_cases
                if top_pattern in (f.error_message or "")
            )
            pattern_ratio = matching / total_failures
            return min(1.0, 0.4 + pattern_ratio * 0.6)

        return 0.4

    def _extract_common_error_patterns(self, error_messages: list[str], top_n: int = 5) -> list[str]:
        """Extract the most common error patterns from a list of error messages.

        Uses the last non-empty line of each error (typically the actual exception)
        as the pattern key, then returns the top-N most frequent patterns.
        """
        if not error_messages:
            return []

        signatures: list[str] = []
        for msg in error_messages:
            lines = [line.strip() for line in msg.strip().split("\n") if line.strip()]
            sig = lines[-1][:200] if lines else msg[:200]
            signatures.append(sig)

        counter = Counter(signatures)
        return [pattern for pattern, _count in counter.most_common(top_n)]
