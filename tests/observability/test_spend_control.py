"""Unit tests for Four-Tier Progressive Spend Control and Soft Quota Intervention Engine."""

import pytest
from myrm_agent_harness.observability.spend_control import (
    FleetQuotaItem,
    FourTierSpendControlEngine,
    InterventionAction,
    SpendControlConfig,
    SpendInterventionDecision,
    SpendInterventionTier,
)


def test_spend_control_normal_allowance():
    engine = FourTierSpendControlEngine(
        SpendControlConfig(tier1_ratio=0.70, tier2_ratio=0.90)
    )
    # $5 spend on $10 limit = 50% (< 70%)
    decision = engine.evaluate(
        current_spend_usd=5.0, quota_limit_usd=10.0, session_id="sess_1"
    )

    assert decision.tier == SpendInterventionTier.TIER_1_VISIBILITY
    assert decision.action == InterventionAction.ALLOW
    assert not decision.is_blocked
    assert decision.spend_ratio == 0.5


def test_tier_1_visibility_and_downgrade_recommendation():
    engine = FourTierSpendControlEngine(
        SpendControlConfig(tier1_ratio=0.70, tier2_ratio=0.90)
    )
    # $7.5 spend on $10 limit = 75% (>= 70% and < 90%)
    decision = engine.evaluate(
        current_spend_usd=7.5, quota_limit_usd=10.0, session_id="sess_2"
    )

    assert decision.tier == SpendInterventionTier.TIER_1_VISIBILITY
    assert decision.action == InterventionAction.RECOMMEND_DOWNGRADE
    assert not decision.is_blocked
    assert decision.downgrade_model_id == "gpt-4o-mini"
    assert "Spend velocity warning" in decision.message


def test_tier_2_soft_gate_and_self_confirmation_bypass():
    engine = FourTierSpendControlEngine(
        SpendControlConfig(tier2_ratio=0.90, tier3_ratio=1.00)
    )
    # $9.5 spend on $10 limit = 95% (>= 90% and < 100%)
    decision1 = engine.evaluate(
        current_spend_usd=9.5, quota_limit_usd=10.0, session_id="sess_3"
    )

    assert decision1.tier == SpendInterventionTier.TIER_2_SOFT_GATE
    assert decision1.action == InterventionAction.REQUIRE_CONFIRMATION
    assert decision1.is_blocked
    assert decision1.bypass_token is not None

    # Developer self-confirms the soft gate
    success = engine.confirm_soft_gate(
        session_id="sess_3", bypass_token=decision1.bypass_token
    )
    assert success is True

    # Re-evaluate session: should now be unblocked
    decision2 = engine.evaluate(
        current_spend_usd=9.5, quota_limit_usd=10.0, session_id="sess_3"
    )
    assert decision2.tier == SpendInterventionTier.TIER_2_SOFT_GATE
    assert decision2.action == InterventionAction.ALLOW
    assert not decision2.is_blocked
    assert decision2.bypass_token == decision1.bypass_token


def test_tier_3_seamless_auto_downgrade_to_economy_model():
    engine = FourTierSpendControlEngine(
        SpendControlConfig(
            tier3_ratio=1.00, tier4_ratio=1.30, downgrade_model_id="claude-3-5-haiku"
        )
    )
    # $11.0 spend on $10 limit = 110% (>= 100% and < 130%)
    decision = engine.evaluate(
        current_spend_usd=11.0, quota_limit_usd=10.0, session_id="sess_4"
    )

    assert decision.tier == SpendInterventionTier.TIER_3_AUTO_DOWNGRADE
    assert decision.action == InterventionAction.SWITCH_MODEL
    assert not decision.is_blocked
    assert decision.downgrade_model_id == "claude-3-5-haiku"
    assert "Seamlessly auto-downgrading" in decision.message


def test_tier_4_critical_pause_and_admin_approval():
    engine = FourTierSpendControlEngine(SpendControlConfig(tier4_ratio=1.30))
    # $14.0 spend on $10 limit = 140% (>= 130%)
    decision1 = engine.evaluate(
        current_spend_usd=14.0, quota_limit_usd=10.0, session_id="sess_5"
    )

    assert decision1.tier == SpendInterventionTier.TIER_4_CRITICAL_PAUSE
    assert decision1.action == InterventionAction.PAUSE_FOR_APPROVAL
    assert decision1.is_blocked
    assert decision1.approval_token is not None

    # Admin executive override sign-off
    appr_ok = engine.approve_tier4_pause(
        session_id="sess_5", approval_token=decision1.approval_token
    )
    assert appr_ok is True

    # Re-evaluate session after override
    decision2 = engine.evaluate(
        current_spend_usd=14.0, quota_limit_usd=10.0, session_id="sess_5"
    )
    assert decision2.tier == SpendInterventionTier.TIER_4_CRITICAL_PAUSE
    assert decision2.action == InterventionAction.ALLOW
    assert not decision2.is_blocked


def test_fleet_quota_deck_attribution_and_utilization():
    engine = FourTierSpendControlEngine()

    item1 = engine.record_fleet_spend(
        dimension="agent_profile",
        identifier="researcher_agent",
        spend_usd=4.5,
        quota_usd=5.0,
        active_sessions=3,
    )
    assert item1.utilization_pct == 90.0
    assert item1.tier == SpendInterventionTier.TIER_2_SOFT_GATE

    item2 = engine.record_fleet_spend(
        dimension="member",
        identifier="dev_alice",
        spend_usd=12.0,
        quota_usd=10.0,
        active_sessions=1,
    )
    assert item2.utilization_pct == 120.0
    assert item2.tier == SpendInterventionTier.TIER_3_AUTO_DOWNGRADE

    deck = engine.get_fleet_quota_deck()
    assert len(deck) == 2
    assert deck[0].identifier == "dev_alice"  # higher spend first

    filtered = engine.get_fleet_quota_deck(dimension="agent_profile")
    assert len(filtered) == 1
    assert filtered[0].identifier == "researcher_agent"
