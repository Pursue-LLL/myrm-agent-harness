"""Tests for ThresholdQualityGate."""

import pytest

from myrm_agent_harness.agent.skills.sync.quality_gate import ThresholdQualityGate


@pytest.fixture
def gate() -> ThresholdQualityGate:
    return ThresholdQualityGate(min_executions=3, min_effective_rate=0.7)


@pytest.mark.asyncio
async def test_passes_with_good_metrics(gate: ThresholdQualityGate) -> None:
    verdict = await gate.evaluate(
        skill_name="good_skill",
        skill_content="# SKILL.md\n\nDoes something useful",
        effective_rate=0.85,
        total_executions=10,
    )
    assert verdict.passed is True
    assert verdict.score > 0


@pytest.mark.asyncio
async def test_rejects_low_effective_rate(gate: ThresholdQualityGate) -> None:
    verdict = await gate.evaluate(
        skill_name="bad_skill",
        skill_content="# SKILL.md\n\nUnreliable",
        effective_rate=0.3,
        total_executions=5,
    )
    assert verdict.passed is False
    assert any("effective rate" in r.lower() for r in verdict.reasons)


@pytest.mark.asyncio
async def test_rejects_insufficient_executions(gate: ThresholdQualityGate) -> None:
    verdict = await gate.evaluate(
        skill_name="new_skill",
        skill_content="# SKILL.md\n\nToo new",
        effective_rate=0.9,
        total_executions=1,
    )
    assert verdict.passed is False
    assert any("insufficient" in r.lower() for r in verdict.reasons)


@pytest.mark.asyncio
async def test_rejects_empty_content(gate: ThresholdQualityGate) -> None:
    verdict = await gate.evaluate(
        skill_name="empty_skill",
        skill_content="   ",
        effective_rate=1.0,
        total_executions=100,
    )
    assert verdict.passed is False
    assert any("empty" in r.lower() for r in verdict.reasons)


@pytest.mark.asyncio
async def test_boundary_values(gate: ThresholdQualityGate) -> None:
    """Exactly at threshold should pass."""
    verdict = await gate.evaluate(
        skill_name="boundary_skill",
        skill_content="# SKILL.md\n\nAt boundary",
        effective_rate=0.7,
        total_executions=3,
    )
    assert verdict.passed is True
