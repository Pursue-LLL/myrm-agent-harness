"""Skill evolution capacity governor.

Caps how many skills self-evolution may accumulate. The cap guards against runaway
auto-capture and keeps the library reviewable. It is deliberately count-only: skill
bodies load on demand, so token volume is budgeted where bodies are loaded (context
compaction), not by library size.

[INPUT]
- agent.skills.evolution.core.types::EvolutionType (POS: Evolution core types)

[OUTPUT]
- BudgetStatus: Enum for capacity states (NORMAL, FULL)
- BudgetCheckResult: Result model of a capacity check
- SkillBudgetConfig: Library size cap
- SkillBudgetGovernor: Core capacity governor class

[POS]
Core capacity governor for skill self-evolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionType

__all__ = [
    "BudgetCheckResult",
    "BudgetStatus",
    "SkillBudgetConfig",
    "SkillBudgetGovernor",
]

# Repairs rewrite an existing skill, so they never grow the library.
_REPAIR_TYPES = frozenset({EvolutionType.FIX, EvolutionType.OPTIMIZE_DESCRIPTION})


class BudgetStatus(StrEnum):
    """Capacity status of the skill library."""

    NORMAL = "normal"
    FULL = "full"


@dataclass(frozen=True)
class SkillBudgetConfig:
    """Capacity cap for the skill library."""

    max_skill_count: int = 50


@dataclass(frozen=True)
class BudgetCheckResult:
    """Detailed result of a capacity check."""

    allowed: bool
    status: BudgetStatus
    current_count: int
    max_count: int
    message: str


class SkillBudgetGovernor:
    """Governor pausing new-skill evolution once the library is full."""

    def __init__(self, config: SkillBudgetConfig | None = None) -> None:
        self.config = config or SkillBudgetConfig()

    def check_budget(self, evolution_type: EvolutionType, current_count: int) -> BudgetCheckResult:
        """Decide whether an evolution may proceed given the active skill count.

        Repairs (FIX, OPTIMIZE_DESCRIPTION) are always allowed so bug fixes are never
        starved; they still report a full library. Every other evolution type adds a
        skill and is paused once the library holds ``max_skill_count`` skills.
        """
        max_count = self.config.max_skill_count
        if current_count < max_count:
            return BudgetCheckResult(
                allowed=True,
                status=BudgetStatus.NORMAL,
                current_count=current_count,
                max_count=max_count,
                message="Capacity healthy.",
            )

        is_repair = evolution_type in _REPAIR_TYPES
        verdict = "Repair evolution granted." if is_repair else "New skill evolution paused."
        return BudgetCheckResult(
            allowed=is_repair,
            status=BudgetStatus.FULL,
            current_count=current_count,
            max_count=max_count,
            message=f"Skill library is full ({current_count}/{max_count} skills). {verdict}",
        )
