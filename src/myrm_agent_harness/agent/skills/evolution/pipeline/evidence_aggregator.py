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
    """

    def __init__(self, store: SkillStore, lookback_days: int = 7) -> None:
        self._store = store
        self._lookback_days = lookback_days

    def aggregate(self) -> list[SkillEvidenceGroup]:
        """Aggregate recent execution analyses into evidence groups.

        Returns:
            List of SkillEvidenceGroup, one per skill that has recent activity.
        """
        raw_groups = self._store.get_recent_analyses_grouped(days=self._lookback_days)

        if not raw_groups:
            logger.debug("No recent execution analyses to aggregate")
            return []

        evidence_groups: list[SkillEvidenceGroup] = []

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

            group = SkillEvidenceGroup(
                skill_id=skill_id,
                skill_name=skill_record.name,
                success_cases=success_cases,
                failure_cases=failure_cases,
                metrics_snapshot=skill_record.metrics,
                common_error_patterns=common_errors,
            )
            evidence_groups.append(group)

        logger.info(
            "Aggregated evidence for %d skills (%d with sufficient evidence)",
            len(evidence_groups),
            sum(1 for g in evidence_groups if g.has_sufficient_evidence()),
        )

        return evidence_groups

    def _extract_common_error_patterns(
        self, error_messages: list[str], top_n: int = 5
    ) -> list[str]:
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
