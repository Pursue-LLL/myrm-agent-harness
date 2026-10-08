"""
[POS] tests/unit/test_autonomous_signing_airgap_suite.py
[INPUT] myrm_agent_harness.core.security.autonomous_signing_airgap
[OUTPUT] Unit tests for AutonomousSigningAirgapFacade
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.autonomous_signing_airgap import (
    AutonomousSigningAirgapFacade,
    SigningDecisionStatus,
    SigningQuotaConfig,
    TransactionPayload,
)


def test_silent_authorized_transaction() -> None:
    """Test standard headless autonomous signing for low-value whitelisted transaction."""
    config = SigningQuotaConfig(
        single_tx_limit=100.0,
        daily_cumulative_limit=500.0,
        trusted_recipients=("0xTrustedContractA", "0xTrustedVendorB"),
    )
    facade = AutonomousSigningAirgapFacade(quota_config=config)

    tx = TransactionPayload(
        tx_id="tx-001",
        recipient="0xTrustedContractA",
        amount=25.0,
        currency="USDC",
        chain_or_network="base",
        call_data_summary="swap(USDC, ETH, 25.0)",
        metadata={"caller": "delta_neutral_arbitrage_robot"},
    )

    verdict = facade.evaluate_and_sign(tx)
    assert verdict.decision == SigningDecisionStatus.SILENT_AUTHORIZED
    assert verdict.is_approved_to_sign is True
    assert verdict.signature_token is not None
    assert len(verdict.signature_token) == 64
    assert facade.current_daily_spent == 25.0
    assert verdict.remaining_daily_allowance == 475.0


def test_untrusted_recipient_rejection() -> None:
    """Test strict rejection of non-whitelisted recipient addresses."""
    config = SigningQuotaConfig(
        single_tx_limit=100.0,
        daily_cumulative_limit=500.0,
        trusted_recipients=("0xLegitExchange",),
    )
    facade = AutonomousSigningAirgapFacade(quota_config=config)

    tx = TransactionPayload(
        tx_id="tx-002",
        recipient="0xPhishingDrainerAddress",
        amount=10.0,
        currency="USDC",
        chain_or_network="ethereum",
        call_data_summary="transfer(0xPhishingDrainerAddress, 10.0)",
    )

    verdict = facade.evaluate_and_sign(tx)
    assert verdict.decision == SigningDecisionStatus.REJECTED_UNTRUSTED_RECIPIENT
    assert verdict.is_approved_to_sign is False
    assert verdict.signature_token is None
    assert facade.current_daily_spent == 0.0
    assert facade.metrics.rejected_untrusted_total == 1


def test_single_limit_step_up_hitl_and_approval() -> None:
    """Test step-up human-in-the-loop escalation when single tx exceeds silent threshold."""
    config = SigningQuotaConfig(
        single_tx_limit=100.0,
        daily_cumulative_limit=500.0,
        trusted_recipients=("0xCloudProviderEscrow",),
    )
    facade = AutonomousSigningAirgapFacade(quota_config=config)

    # 150 > single_tx_limit(100), but within 3x limit (300) -> Step-Up HITL
    tx = TransactionPayload(
        tx_id="tx-003",
        recipient="0xCloudProviderEscrow",
        amount=150.0,
        currency="USDC",
        chain_or_network="arbitrum",
        call_data_summary="monthly_server_settlement()",
    )

    verdict = facade.evaluate_and_sign(tx)
    assert verdict.decision == SigningDecisionStatus.REQUIRE_HITL_STEP_UP
    assert verdict.is_approved_to_sign is False
    assert verdict.signature_token is None
    assert facade.current_daily_spent == 0.0

    pending = facade.list_pending_hitl_txs()
    assert len(pending) == 1
    assert pending[0].tx_id == "tx-003"

    # Human operator approves the stepped-up transaction
    approved = facade.approve_stepped_up_tx(
        "tx-003", approver_note="Approved by Ops Admin"
    )
    assert approved is not None
    assert approved.decision == SigningDecisionStatus.SILENT_AUTHORIZED
    assert approved.is_approved_to_sign is True
    assert approved.signature_token is not None
    assert facade.current_daily_spent == 150.0
    assert len(facade.list_pending_hitl_txs()) == 0


def test_severe_quota_exceeded_rejection() -> None:
    """Test hard rejection when single tx is >3x limit or daily cumulative quota is exceeded."""
    config = SigningQuotaConfig(
        single_tx_limit=100.0,
        daily_cumulative_limit=200.0,
        trusted_recipients=(),  # empty whitelist permits any recipient up to quota
    )
    facade = AutonomousSigningAirgapFacade(quota_config=config)

    # 1. Severe single limit breach (>300)
    tx_huge = TransactionPayload(
        tx_id="tx-huge",
        recipient="0xAnyTarget",
        amount=350.0,
        currency="USDC",
        chain_or_network="base",
        call_data_summary="drain()",
    )
    v_huge = facade.evaluate_and_sign(tx_huge)
    assert v_huge.decision == SigningDecisionStatus.REJECTED_QUOTA_EXCEEDED
    assert v_huge.is_approved_to_sign is False

    # 2. Cumulative breach: 2 transactions of 100 each fill 200, 3rd fails
    t1 = facade.evaluate_and_sign(
        TransactionPayload(
            tx_id="t1",
            recipient="0xAnyTarget",
            amount=100.0,
            currency="USDC",
            chain_or_network="base",
            call_data_summary="pay_1",
        )
    )
    assert t1.is_approved_to_sign is True

    t2 = facade.evaluate_and_sign(
        TransactionPayload(
            tx_id="t2",
            recipient="0xAnyTarget",
            amount=100.0,
            currency="USDC",
            chain_or_network="base",
            call_data_summary="pay_2",
        )
    )
    assert t2.is_approved_to_sign is True

    t3 = facade.evaluate_and_sign(
        TransactionPayload(
            tx_id="t3",
            recipient="0xAnyTarget",
            amount=1.0,
            currency="USDC",
            chain_or_network="base",
            call_data_summary="pay_3",
        )
    )
    assert t3.decision == SigningDecisionStatus.REJECTED_QUOTA_EXCEEDED
    assert t3.is_approved_to_sign is False


def test_emergency_kill_switch_freeze_and_release() -> None:
    """Test emergency wallet kill-switch freeze asserting 100% hard physical cutoff."""
    config = SigningQuotaConfig(single_tx_limit=100.0, daily_cumulative_limit=500.0)
    facade = AutonomousSigningAirgapFacade(quota_config=config)

    # Engage kill-switch
    facade.trigger_kill_switch(reason="Suspected anomalous agent behavior")
    assert facade.is_kill_switch_active is True
    assert facade.kill_switch_reason == "Suspected anomalous agent behavior"

    tx = TransactionPayload(
        tx_id="tx-frozen",
        recipient="0xSafeVendor",
        amount=10.0,
        currency="USDC",
        chain_or_network="base",
        call_data_summary="buy()",
    )
    v_frozen = facade.evaluate_and_sign(tx)
    assert v_frozen.decision == SigningDecisionStatus.FROZEN_BY_KILL_SWITCH
    assert v_frozen.is_approved_to_sign is False
    assert v_frozen.signature_token is None

    # Release kill-switch
    facade.release_kill_switch()
    assert facade.is_kill_switch_active is False

    v_restored = facade.evaluate_and_sign(tx)
    assert v_restored.decision == SigningDecisionStatus.SILENT_AUTHORIZED
    assert v_restored.is_approved_to_sign is True
