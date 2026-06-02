"""Skill quality tracking and FIX evolution triggering.

Monitors skill execution results and identifies skills needing repair.
Core functionality for data-driven skill optimization (收益8/10).

[INPUT]
- agent.skills.evolution.core.types::ExecutionAnalysis, (POS: Data types for skill evolution system.)
- agent.skills.evolution.db.store::SkillStore (POS: SQLite persistence for skill evolution system.)

[OUTPUT]
- SkillExecutionResult: Result of a single skill execution.
- SkillQualityTracker: Track skill quality metrics and trigger FIX evolution.

[POS]
Skill quality tracking and FIX evolution triggering.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from myrm_agent_harness.agent.skills.evolution.core.types import ExecutionAnalysis, SkillMetrics, SkillRecord
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore

logger = logging.getLogger(__name__)

__all__ = ["SkillExecutionResult", "SkillQualityTracker"]


@dataclass
class SkillExecutionResult:
    """Result of a single skill execution."""

    skill_id: str
    success: bool
    error_message: str = ""
    execution_time_ms: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)


class SkillQualityTracker:
    """Track skill quality metrics and trigger FIX evolution.

    Responsibilities:
    1. Record execution results (success/failure)
    2. Update quality metrics in store
    3. Identify skills needing FIX evolution

    Usage:
        tracker = SkillQualityTracker(store)
        await tracker.record_execution(result)
        skills_to_fix = await tracker.get_skills_needing_fix()
    """

    def __init__(self, store: SkillStore):
        """Initialize tracker.

        Args:
            store: SkillStore instance for persistence
        """
        self._store = store

    async def record_execution(self, result: SkillExecutionResult) -> SkillMetrics:
        """Record skill execution result and update metrics.

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

        task_id = result.context.get("task_id", str(uuid.uuid4()))
        task_context = result.context.get("task_intent", "")

        # Update metrics
        if result.success:
            skill.metrics.record_success()
            logger.debug(
                "Skill %s succeeded (success_rate=%.2f, usage=%d)",
                result.skill_id,
                skill.metrics.success_rate,
                skill.metrics.usage_count,
            )
        else:
            skill.metrics.record_failure()
            logger.warning(
                "Skill %s failed (success_rate=%.2f, consecutive_failures=%d): %s",
                result.skill_id,
                skill.metrics.success_rate,
                skill.metrics.consecutive_failures,
                result.error_message,
            )

        # Save ExecutionAnalysis for both success and failure to enable evidence-based evolution
        analysis = ExecutionAnalysis(
            skill_id=result.skill_id,
            task_id=task_id,
            success=result.success,
            error_message=result.error_message if not result.success else "",
            task_context=task_context,
        )
        await self._store.save_analysis(analysis)

        # Persist updated metrics
        await self._store.update_metrics(result.skill_id, skill.metrics)

        # Log if FIX evolution should be triggered
        if skill.metrics.should_trigger_fix():
            logger.warning(
                "Skill %s needs FIX evolution (success_rate=%.2f, consecutive_failures=%d)",
                result.skill_id,
                skill.metrics.success_rate,
                skill.metrics.consecutive_failures,
            )

        return skill.metrics

    async def get_skills_needing_fix(self, threshold: float = 0.5) -> list[SkillRecord]:
        """Find skills that need FIX evolution.

        Args:
            threshold: Success rate threshold (default 0.5)

        Returns:
            List of skills needing FIX evolution, sorted by urgency
            (consecutive failures first, then by success rate)
        """
        skills = self._store.get_skills_needing_fix(threshold)
        if skills:
            logger.info("Found %d skills needing FIX evolution (threshold=%.2f)", len(skills), threshold)
        return skills

    def get_quality_report(self) -> dict[str, float | int]:
        """Generate quality metrics report for all active skills.

        Returns:
            Dict with aggregate metrics:
            - total_skills: Total active skills
            - avg_success_rate: Average success rate
            - skills_needing_fix: Count of skills below threshold
            - total_executions: Total skill executions
        """
        skills = self._store.get_active_skills()

        if not skills:
            return {
                "total_skills": 0,
                "avg_success_rate": 0.0,
                "skills_needing_fix": 0,
                "total_executions": 0,
            }

        total_success_rate = sum(s.metrics.success_rate for s in skills)
        total_executions = sum(s.metrics.usage_count for s in skills)
        skills_with_low_rate = sum(1 for s in skills if s.metrics.should_trigger_fix())

        report = {
            "total_skills": len(skills),
            "avg_success_rate": total_success_rate / len(skills),
            "skills_needing_fix": skills_with_low_rate,
            "total_executions": total_executions,
        }

        logger.info(
            "Quality report: %d skills, avg_success_rate=%.2f, %d need FIX, %d total executions",
            report["total_skills"],
            report["avg_success_rate"],
            report["skills_needing_fix"],
            report["total_executions"],
        )

        return report

    async def batch_record_executions(self, results: list[SkillExecutionResult]) -> dict[str, SkillMetrics]:
        """Record multiple execution results efficiently.

        Args:
            results: List of execution results

        Returns:
            Dict mapping skill_id to updated metrics
        """
        updated_metrics = {}
        for result in results:
            try:
                metrics = await self.record_execution(result)
                updated_metrics[result.skill_id] = metrics
            except ValueError as e:
                logger.error("Failed to record execution: %s", e)
                continue

        logger.debug("Batch recorded %d/%d executions", len(updated_metrics), len(results))
        return updated_metrics
