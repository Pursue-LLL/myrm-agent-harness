"""Unit tests for the count-only SkillBudgetGovernor and CompactorPreflightFence."""

import pytest

from myrm_agent_harness.agent.context_management.infra.compactor_guard import (
    CompactorPreflightFence,
)
from myrm_agent_harness.agent.skills.evolution.core.budget_governor import (
    BudgetStatus,
    SkillBudgetConfig,
    SkillBudgetGovernor,
)
from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionType

_NEW_SKILL_TYPES = (EvolutionType.CAPTURED, EvolutionType.DERIVED)
_REPAIR_TYPES = (EvolutionType.FIX, EvolutionType.OPTIMIZE_DESCRIPTION)


def test_default_cap_is_fifty_skills() -> None:
    assert SkillBudgetConfig().max_skill_count == 50


@pytest.mark.parametrize("evolution_type", _NEW_SKILL_TYPES)
def test_new_skill_generation_is_allowed_below_the_cap(evolution_type: EvolutionType) -> None:
    governor = SkillBudgetGovernor(SkillBudgetConfig(max_skill_count=10))

    result = governor.check_budget(evolution_type=evolution_type, current_count=9)

    assert result.allowed is True
    assert result.status == BudgetStatus.NORMAL
    assert (result.current_count, result.max_count) == (9, 10)


@pytest.mark.parametrize("evolution_type", _NEW_SKILL_TYPES)
@pytest.mark.parametrize("current_count", [10, 11])
def test_new_skill_generation_is_paused_once_the_library_is_full(
    evolution_type: EvolutionType, current_count: int
) -> None:
    governor = SkillBudgetGovernor(SkillBudgetConfig(max_skill_count=10))

    result = governor.check_budget(evolution_type=evolution_type, current_count=current_count)

    assert result.allowed is False
    assert result.status == BudgetStatus.FULL
    assert "paused" in result.message


@pytest.mark.parametrize("evolution_type", _REPAIR_TYPES)
@pytest.mark.parametrize("current_count", [9, 10, 11])
def test_repairs_are_never_blocked_by_the_cap(evolution_type: EvolutionType, current_count: int) -> None:
    governor = SkillBudgetGovernor(SkillBudgetConfig(max_skill_count=10))

    result = governor.check_budget(evolution_type=evolution_type, current_count=current_count)

    assert result.allowed is True


def test_repair_at_the_cap_reports_the_full_library() -> None:
    governor = SkillBudgetGovernor(SkillBudgetConfig(max_skill_count=10))

    result = governor.check_budget(evolution_type=EvolutionType.FIX, current_count=10)

    assert result.status == BudgetStatus.FULL
    assert "Repair evolution granted" in result.message


def test_compactor_preflight_fence() -> None:
    fence = CompactorPreflightFence(safe_watermark_ratio=0.85)

    # Safe
    v_safe = fence.evaluate_safety(
        messages_tokens=50_000,
        loaded_skills_tokens=10_000,
        prompt_overhead=2_000,
        max_context_tokens=100_000,
    )
    assert v_safe.is_safe is True
    assert v_safe.action_recommended == "proceed"

    # Exceed watermark but within physical window
    v_warn = fence.evaluate_safety(
        messages_tokens=75_000,
        loaded_skills_tokens=12_000,
        prompt_overhead=2_000,
        max_context_tokens=100_000,
    )
    assert v_warn.is_safe is False
    assert v_warn.action_recommended == "slice_history"

    # Complete overflow
    v_overflow = fence.evaluate_safety(
        messages_tokens=95_000,
        loaded_skills_tokens=10_000,
        prompt_overhead=2_000,
        max_context_tokens=100_000,
    )
    assert v_overflow.is_safe is False
    assert v_overflow.action_recommended == "emergency_trim"
