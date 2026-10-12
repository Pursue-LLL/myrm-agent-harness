"""Skill execution ledger.

Counts skill execution outcomes into the persistent per-skill metrics. Counting
only: repair decisions are made elsewhere (failure events, trace slices and the
approval flow's effective-rate signal), never by this ledger.

[INPUT]
- agent.skills.evolution.core.types::SkillMetrics (POS: Data types for skill evolution system.)
- agent.skills.evolution.db.store::SkillStore (POS: SQLite persistence for skill evolution system.)

[OUTPUT]
- SkillExecutionResult: Outcome of a single skill execution.
- SkillQualityTracker: Records execution outcomes into the skill metrics ledger.

[POS]
Skill execution ledger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from myrm_agent_harness.agent.skills.evolution.core.types import SkillMetrics
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore

logger = logging.getLogger(__name__)

__all__ = ["SkillExecutionResult", "SkillQualityTracker"]


@dataclass
class SkillExecutionResult:
    """Outcome of a single skill execution."""

    skill_id: str
    success: bool
    error_message: str = ""


class SkillQualityTracker:
    """Records skill execution outcomes into the persisted metrics."""

    def __init__(self, store: SkillStore):
        """Initialize tracker.

        Args:
            store: SkillStore instance for persistence
        """
        self._store = store

    async def record_execution(self, result: SkillExecutionResult) -> SkillMetrics:
        """Record one execution outcome and persist the updated metrics.

        Args:
            result: Execution result to record

        Returns:
            Updated SkillMetrics

        Raises:
            ValueError: If skill not found
        """
        skill = self._store.get_skill(result.skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {result.skill_id}")

        skill.metrics.record_applied(success=result.success)
        if result.success:
            logger.debug(
                "Skill %s succeeded (success_rate=%.2f, usage=%d)",
                result.skill_id,
                skill.metrics.success_rate,
                skill.metrics.usage_count,
            )
        else:
            logger.warning(
                "Skill %s failed (success_rate=%.2f, consecutive_failures=%d): %s",
                result.skill_id,
                skill.metrics.success_rate,
                skill.metrics.consecutive_failures,
                result.error_message,
            )

        await self._store.update_metrics(result.skill_id, skill.metrics)
        return skill.metrics
