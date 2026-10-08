"""Unit tests for Autonomous Bot Asset Security Boundary and Wallet Credential Air-Gap Guard suite.

[POS]
Harness core security test suite verifying air-gapped private key isolation,
autonomous micro-transaction limits, human two-person confirmation cards, and daily spend circuit breakers.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.financial_boundary import (
    AirGappedCredentialViolationError,
    FinancialActionBoundaryGuard,
    FinancialActionType,
    FinancialTransactionIntent,
    SpendingCeilingPolicy,
)


def test_air_gap_credential_violation_detection() -> None:
    guard = FinancialActionBoundaryGuard()

    # 1. EVM private key detection
    raw_evm_key = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f36088a"
    with pytest.raises(AirGappedCredentialViolationError):
        guard.assert_no_private_keys(f"Here is the bot key: {raw_evm_key}")

    # 2. Seed phrase detection
    seed_phrase = "mnemonic: apple banana cherry dog elephant fox grape horse igloo jaguar kite lemon"
    with pytest.raises(AirGappedCredentialViolationError):
        guard.assert_no_private_keys(seed_phrase)

    # 3. Clean text passes
    guard.assert_no_private_keys("Watcher address: 0x71C8451C3D4324472CaBf11d624c1e40004f1234")


def test_micro_transaction_autonomous_execution() -> None:
    policy = SpendingCeilingPolicy(
        daily_ceiling_usd=50.0,
        single_transaction_ceiling_usd=5.0,
    )
    guard = FinancialActionBoundaryGuard(policy)

    intent = FinancialTransactionIntent(
        intent_id="intent_gas_01",
        task_id="task_auto_pay",
        action_type=FinancialActionType.TRANSFER,
        asset_symbol="ETH",
        amount=0.001,
        estimated_usd_value=2.50,
        recipient_address="0x1111111111111111111111111111111111111111",
        justification="Automated gas fee top-up for monitoring probe",
    )

    res = guard.evaluate_intent(intent)
    assert res.permitted_autonomous_execution is True
    assert res.requires_human_confirmation is False
    assert res.circuit_breaker_triggered is False
    assert res.current_daily_spend_usd == 2.50
    assert res.remaining_daily_limit_usd == 47.50


def test_single_transaction_threshold_triggers_confirmation_card() -> None:
    policy = SpendingCeilingPolicy(
        daily_ceiling_usd=100.0,
        single_transaction_ceiling_usd=5.0,
    )
    guard = FinancialActionBoundaryGuard(policy)

    intent = FinancialTransactionIntent(
        intent_id="intent_buy_02",
        task_id="task_trade",
        action_type=FinancialActionType.SWAP,
        asset_symbol="USDC",
        amount=25.0,
        estimated_usd_value=25.0,
        recipient_address="0x2222222222222222222222222222222222222222",
        justification="Acquiring utility token for liquidity indexing",
    )

    res = guard.evaluate_intent(intent)
    assert res.permitted_autonomous_execution is False
    assert res.requires_human_confirmation is True
    assert res.confirmation_card_id is not None
    card_id = res.confirmation_card_id

    # Check card
    card = guard.get_card(card_id)
    assert card is not None
    assert card.status == "pending"

    # Human approves card
    approved_card = guard.approve_card(card_id)
    assert approved_card.status == "approved"
    assert guard.get_current_daily_spend() == 25.0


def test_daily_spend_ceiling_circuit_breaker() -> None:
    policy = SpendingCeilingPolicy(
        daily_ceiling_usd=10.0,
        single_transaction_ceiling_usd=15.0,
    )
    guard = FinancialActionBoundaryGuard(policy)

    # First transaction spends $8.00
    intent1 = FinancialTransactionIntent(
        intent_id="intent_tx_1",
        task_id="task_limit",
        action_type=FinancialActionType.TRANSFER,
        asset_symbol="USDT",
        amount=8.0,
        estimated_usd_value=8.0,
        recipient_address="0x3333333333333333333333333333333333333333",
        justification="Initial test spend",
    )
    res1 = guard.evaluate_intent(intent1)
    assert res1.permitted_autonomous_execution is True

    # Second transaction attempts $5.00 ($8 + $5 = $13 > $10) -> circuit breaker!
    intent2 = FinancialTransactionIntent(
        intent_id="intent_tx_2",
        task_id="task_limit",
        action_type=FinancialActionType.TRANSFER,
        asset_symbol="USDT",
        amount=5.0,
        estimated_usd_value=5.0,
        recipient_address="0x3333333333333333333333333333333333333333",
        justification="Second spend exceeding ceiling",
    )
    res2 = guard.evaluate_intent(intent2)
    assert res2.permitted_autonomous_execution is False
    assert res2.circuit_breaker_triggered is True
    assert "Daily ceiling circuit breaker triggered" in res2.reason


def test_unwhitelisted_asset_rejection() -> None:
    guard = FinancialActionBoundaryGuard()

    intent = FinancialTransactionIntent(
        intent_id="intent_scam_01",
        task_id="task_scam",
        action_type=FinancialActionType.BUY,
        asset_symbol="UNKNOWN_MEME_COIN",
        amount=100000.0,
        estimated_usd_value=1.0,
        recipient_address="0x4444444444444444444444444444444444444444",
        justification="Pump and dump scan",
    )

    res = guard.evaluate_intent(intent)
    assert res.permitted_autonomous_execution is False
    assert "not whitelisted" in res.reason
