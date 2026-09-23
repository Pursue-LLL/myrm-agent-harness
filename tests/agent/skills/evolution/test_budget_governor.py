"""Unit tests for SkillBudgetGovernor and CompactorPreflightFence."""

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.agent.context_management.infra.compactor_guard import (
    CompactorPreflightFence,
)
from myrm_agent_harness.agent.skills.evolution.core.budget_governor import (
    BudgetStatus,
    SkillBudgetConfig,
    SkillBudgetGovernor,
)
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    SkillMetrics,
    SkillRecord,
)


def test_budget_governor_normal_flow() -> None:
    config = SkillBudgetConfig(max_tokens=10_000, soft_limit_ratio=0.8, max_skill_count=10)
    governor = SkillBudgetGovernor(config)

    # 1. Healthy state
    res = governor.check_budget(
        evolution_type=EvolutionType.CAPTURED,
        current_tokens=2_000,
        current_count=2,
        estimated_new_tokens=500,
    )
    assert res.allowed is True
    assert res.status == BudgetStatus.NORMAL


def test_budget_governor_soft_limit_warning() -> None:
    config = SkillBudgetConfig(max_tokens=10_000, soft_limit_ratio=0.8, max_skill_count=10)
    governor = SkillBudgetGovernor(config)

    # 2. Soft limit hit (projected tokens = 8200 >= 8000)
    res = governor.check_budget(
        evolution_type=EvolutionType.CAPTURED,
        current_tokens=7_700,
        current_count=3,
        estimated_new_tokens=500,
    )
    assert res.allowed is True
    assert res.status == BudgetStatus.SOFT_LIMIT
    assert "Consolidation recommended" in res.message


def test_budget_governor_hard_limit_block_and_repair_bypass() -> None:
    config = SkillBudgetConfig(max_tokens=10_000, soft_limit_ratio=0.8, max_skill_count=10)
    governor = SkillBudgetGovernor(config)

    # 3. Hard limit exceeded for new skill creation
    res_block = governor.check_budget(
        evolution_type=EvolutionType.CAPTURED,
        current_tokens=9_800,
        current_count=9,
        estimated_new_tokens=500,
    )
    assert res_block.allowed is False
    assert res_block.status == BudgetStatus.HARD_LIMIT
    assert "paused" in res_block.message

    # 4. Self-healing repair (FIX) must be allowed even at hard limit
    res_repair = governor.check_budget(
        evolution_type=EvolutionType.FIX,
        current_tokens=9_800,
        current_count=9,
        estimated_new_tokens=500,
    )
    assert res_repair.allowed is True
    assert res_repair.status == BudgetStatus.HARD_LIMIT
    assert "Repair evolution granted" in res_repair.message


def test_budget_governor_identify_cold_skills() -> None:
    config = SkillBudgetConfig(cold_storage_days=30)
    governor = SkillBudgetGovernor(config)

    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
    old_time = now - timedelta(days=45)
    fresh_time = now - timedelta(days=5)

    from myrm_agent_harness.agent.skills.evolution.core.types import SkillLineage

    cold_skill = SkillRecord(
        skill_id="cold-skill",
        name="Cold Skill",
        description="test",
        content="code",
        path="/tmp/cold.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED),
        created_at=old_time,
        metrics=SkillMetrics(last_success_at=old_time),
    )
    active_skill = SkillRecord(
        skill_id="active-skill",
        name="Active Skill",
        description="test",
        content="code",
        path="/tmp/active.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED),
        created_at=old_time,
        metrics=SkillMetrics(last_success_at=fresh_time),
    )

    cold_list = governor.identify_cold_skills([cold_skill, active_skill], now=now)
    assert len(cold_list) == 1
    assert cold_list[0].skill_id == "cold-skill"


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
