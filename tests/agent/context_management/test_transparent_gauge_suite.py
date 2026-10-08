"""Unit tests for ContextWindowTransparentGaugeAndBudgetBreakdownSuite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    BudgetAnalyzer,
    BudgetSegmentBreakdown,
    BudgetSegmentKind,
    CompactionAdjustmentIntervention,
    ContextWindowTransparentGaugeAndBudgetBreakdownSuite,
    TransparentGaugeReceipt,
    WatermarkAlertLevel,
    WatermarkState,
)


def test_5_segment_budget_breakdown_and_percentage_calculation() -> None:
    """Test precise 5-segment token aggregation and percentage breakdown."""
    suite = ContextWindowTransparentGaugeAndBudgetBreakdownSuite(
        session_id="sess-gauge-001",
        window_capacity_tokens=100000,
        reserve_headroom_tokens=10000,
    )

    suite.set_segment_tokens_directly(BudgetSegmentKind.SYSTEM_INSTRUCTIONS, 5000)
    suite.set_segment_tokens_directly(BudgetSegmentKind.WORKSPACE_RULES, 3000)
    suite.set_segment_tokens_directly(BudgetSegmentKind.DYNAMIC_SKILLS, 12000)
    suite.set_segment_tokens_directly(BudgetSegmentKind.COMPACTED_SUMMARY, 15000)
    suite.set_segment_tokens_directly(BudgetSegmentKind.ACTIVE_TURNS, 25000)

    breakdown = suite.compute_current_breakdown()

    assert breakdown.total_used_tokens == 60000
    assert breakdown.window_capacity_tokens == 100000
    assert breakdown.reserve_headroom_tokens == 10000
    assert breakdown.remaining_available_tokens == 30000
    assert breakdown.utilization_ratio == 0.6000

    percentages = breakdown.get_segment_percentages()
    assert percentages[BudgetSegmentKind.SYSTEM_INSTRUCTIONS.value] == 5.0
    assert percentages[BudgetSegmentKind.WORKSPACE_RULES.value] == 3.0
    assert percentages[BudgetSegmentKind.DYNAMIC_SKILLS.value] == 12.0
    assert percentages[BudgetSegmentKind.COMPACTED_SUMMARY.value] == 15.0
    assert percentages[BudgetSegmentKind.ACTIVE_TURNS.value] == 25.0


def test_watermark_graduated_alert_levels() -> None:
    """Test graduated watermark thresholds: NORMAL, ATTENTION, CRITICAL_WARN, and OVERFLOW_RISK."""
    suite = ContextWindowTransparentGaugeAndBudgetBreakdownSuite(
        session_id="sess-gauge-002",
        window_capacity_tokens=100000,
        reserve_headroom_tokens=10000,
    )

    # 1. Normal state (<70%)
    suite.set_segment_tokens_directly(BudgetSegmentKind.ACTIVE_TURNS, 50000)
    w_normal = suite.evaluate_current_watermark()
    assert w_normal.alert_level == WatermarkAlertLevel.NORMAL
    assert not w_normal.is_compaction_recommended

    # 2. Attention state (70% - 85%)
    suite.set_segment_tokens_directly(BudgetSegmentKind.ACTIVE_TURNS, 75000)
    w_attention = suite.evaluate_current_watermark()
    assert w_attention.alert_level == WatermarkAlertLevel.ATTENTION
    assert not w_attention.is_compaction_recommended

    # 3. Critical warning state (85% - 95%)
    suite.set_segment_tokens_directly(BudgetSegmentKind.ACTIVE_TURNS, 88000)
    w_warn = suite.evaluate_current_watermark()
    assert w_warn.alert_level == WatermarkAlertLevel.CRITICAL_WARN
    assert w_warn.is_compaction_recommended

    # 4. Overflow risk state (>=95%)
    suite.set_segment_tokens_directly(BudgetSegmentKind.ACTIVE_TURNS, 96000)
    w_overflow = suite.evaluate_current_watermark()
    assert w_overflow.alert_level == WatermarkAlertLevel.OVERFLOW_RISK
    assert w_overflow.is_compaction_recommended


def test_manual_compaction_intervention_and_pinning() -> None:
    """Test submitting manual interventions, customized tail retention, and segment pinning."""
    suite = ContextWindowTransparentGaugeAndBudgetBreakdownSuite(
        session_id="sess-gauge-003",
        window_capacity_tokens=128000,
    )

    # Preemptive compaction trigger
    receipt1 = suite.trigger_preemptive_compaction(reason="User clicked manual compress button")
    assert receipt1.active_interventions_count == 1
    assert receipt1.session_id == "sess-gauge-003"

    # Customized intervention with pinning
    intervention = CompactionAdjustmentIntervention(
        preemptive_compaction_requested=True,
        custom_retained_tail_turns=10,
        pinned_segment_ids=["sec-rule-01", "pinned-task-contract"],
        reason="Preserve core task contract and keep 10 recent turns",
    )
    receipt2 = suite.apply_intervention(intervention)
    assert receipt2.active_interventions_count == 2
    assert "sec-rule-01" in suite._pinned_segments
    assert "pinned-task-contract" in suite._pinned_segments


def test_transparent_gauge_receipt_audit_integrity() -> None:
    """Test generating complete and auditable gauge snapshot receipts."""
    suite = ContextWindowTransparentGaugeAndBudgetBreakdownSuite(
        session_id="sess-gauge-004",
        window_capacity_tokens=128000,
    )

    suite.update_system_instructions("You are a helpful assistant with strict coding standards.")
    suite.update_workspace_rules("Rule 1: Always check tests. Rule 2: Strict typing.")
    suite.update_dynamic_skills(["Skill 1: git ops", "Skill 2: browser interaction"])
    suite.update_compacted_summary("Prior conversation summarized accurately.")
    suite.record_active_turn_content("User: Please refactor module A\nAssistant: I will inspect...")

    receipt = suite.generate_gauge_receipt()

    assert receipt.receipt_id.startswith("tgr_")
    assert receipt.session_id == "sess-gauge-004"
    assert receipt.snapshot_timestamp_iso != ""
    assert receipt.breakdown.total_used_tokens > 0
    assert receipt.breakdown.remaining_available_tokens > 0
    assert receipt.watermark.alert_level in list(WatermarkAlertLevel)
