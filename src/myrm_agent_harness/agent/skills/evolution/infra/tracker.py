"""Skill execution ledger.

Counts skill execution outcomes into the persistent per-skill metrics. Counting
only: repair decisions are made elsewhere (failure events, trace slices and the
approval flow's effective-rate signal), never by this ledger.

[INPUT]
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

    async def record_execution(self, result: SkillExecutionResult) -> None:
        """Count one execution outcome.

        Args:
            result: Execution result to record

        Raises:
            ValueError: If skill not found
        """
        if not await self._store.record_execution_outcome(result.skill_id, success=result.success):
            raise ValueError(f"Skill not found: {result.skill_id}")

        logger.debug(
            "Skill %s execution recorded (success=%s)%s",
            result.skill_id,
            result.success,
            f": {result.error_message}" if result.error_message else "",
        )
