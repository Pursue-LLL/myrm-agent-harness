"""Skill evolution budget governor and capacity protection protocol.

Provides proactive capacity guarding for continuous long-running sessions,
preventing unbounded skill accumulation from bloating system prompts and
causing context compaction failure.

[INPUT]
- agent.skills.evolution.core.types::EvolutionType, SkillRecord (POS: Evolution core types)

[OUTPUT]
- BudgetStatus: Enum for budget states (NORMAL, SOFT_LIMIT, HARD_LIMIT)
- BudgetCheckResult: Result model of budget check
- SkillBudgetConfig: Configuration for evolution budget
- SkillBudgetGovernor: Core capacity governor class

[POS]
Core capacity governor for skill self-evolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    SkillRecord,
)

__all__ = [
    "BudgetCheckResult",
    "BudgetStatus",
    "SkillBudgetConfig",
    "SkillBudgetGovernor",
]


class BudgetStatus(StrEnum):
    """Capacity and budget status for skill evolution."""

    NORMAL = "normal"
    SOFT_LIMIT = "soft_limit"
    HARD_LIMIT = "hard_limit"


@dataclass(frozen=True)
class SkillBudgetConfig:
    """Configuration defining capacity thresholds and quotas."""

    max_tokens: int = 40_000
    soft_limit_ratio: float = 0.8
    max_skill_count: int = 50
    cold_storage_days: int = 30

    @property
    def soft_limit_tokens(self) -> int:
        """Token threshold triggering soft warning."""
        return int(self.max_tokens * self.soft_limit_ratio)

    @property
    def soft_limit_count(self) -> int:
        """Count threshold triggering soft warning."""
        return int(self.max_skill_count * self.soft_limit_ratio)


@dataclass(frozen=True)
class BudgetCheckResult:
    """Detailed result of a budget check."""

    allowed: bool
    status: BudgetStatus
    current_tokens: int
    max_tokens: int
    current_count: int
    max_count: int
    message: str


class SkillBudgetGovernor:
    """Governor enforcing proactive capacity boundaries on skill evolution."""

    def __init__(self, config: SkillBudgetConfig | None = None) -> None:
        self.config = config or SkillBudgetConfig()

    def check_budget(
        self,
        evolution_type: EvolutionType,
        current_tokens: int,
        current_count: int,
        estimated_new_tokens: int = 500,
    ) -> BudgetCheckResult:
        """Evaluate if an evolution task is permitted under current capacity limits.

        Self-healing fixes (FIX and OPTIMIZE_DESCRIPTION) are always allowed to ensure
        bug fixes can proceed, but will accurately report current limit status.
        New skill generation (CAPTURED, DERIVED, SLICE_EXTRACTION) is blocked once hard limit is reached.
        """
        is_repair = evolution_type in (
            EvolutionType.FIX,
            EvolutionType.OPTIMIZE_DESCRIPTION,
        )

        projected_tokens = current_tokens + estimated_new_tokens
        projected_count = current_count + (0 if is_repair else 1)

        is_hard_exceeded = (
            projected_tokens > self.config.max_tokens
            or projected_count > self.config.max_skill_count
        )
        is_soft_exceeded = (
            projected_tokens >= self.config.soft_limit_tokens
            or projected_count >= self.config.soft_limit_count
        )

        if is_hard_exceeded:
            if is_repair:
                return BudgetCheckResult(
                    allowed=True,
                    status=BudgetStatus.HARD_LIMIT,
                    current_tokens=current_tokens,
                    max_tokens=self.config.max_tokens,
                    current_count=current_count,
                    max_count=self.config.max_skill_count,
                    message=(
                        f"Hard capacity limit reached ({current_tokens}/{self.config.max_tokens} tok, "
                        f"{current_count}/{self.config.max_skill_count} skills). Repair evolution granted."
                    ),
                )
            return BudgetCheckResult(
                allowed=False,
                status=BudgetStatus.HARD_LIMIT,
                current_tokens=current_tokens,
                max_tokens=self.config.max_tokens,
                current_count=current_count,
                max_count=self.config.max_skill_count,
                message=(
                    f"Hard capacity limit exceeded ({projected_tokens}/{self.config.max_tokens} tok, "
                    f"{projected_count}/{self.config.max_skill_count} skills). New skill evolution paused."
                ),
            )

        if is_soft_exceeded:
            return BudgetCheckResult(
                allowed=True,
                status=BudgetStatus.SOFT_LIMIT,
                current_tokens=current_tokens,
                max_tokens=self.config.max_tokens,
                current_count=current_count,
                max_count=self.config.max_skill_count,
                message=(
                    f"Soft capacity warning ({projected_tokens}/{self.config.max_tokens} tok, "
                    f"{projected_count}/{self.config.max_skill_count} skills). Consolidation recommended."
                ),
            )

        return BudgetCheckResult(
            allowed=True,
            status=BudgetStatus.NORMAL,
            current_tokens=current_tokens,
            max_tokens=self.config.max_tokens,
            current_count=current_count,
            max_count=self.config.max_skill_count,
            message="Capacity healthy.",
        )

    def identify_cold_skills(
        self,
        skills: list[SkillRecord],
        now: datetime | None = None,
    ) -> list[SkillRecord]:
        """Identify inactive skills suitable for cold storage archival."""
        current_time = now or datetime.now(UTC)
        cold_threshold_seconds = self.config.cold_storage_days * 86400
        cold_skills: list[SkillRecord] = []

        for skill in skills:
            reference_time = (
                skill.metrics.last_success_at
                or skill.metrics.last_failure_at
                or skill.updated_at
                or skill.created_at
            )
            if reference_time.tzinfo is None:
                reference_time = reference_time.replace(tzinfo=UTC)

            idle_seconds = (current_time - reference_time).total_seconds()
            if idle_seconds >= cold_threshold_seconds:
                cold_skills.append(skill)

        return cold_skills
