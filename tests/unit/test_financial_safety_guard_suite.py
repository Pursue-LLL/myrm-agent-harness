"""Unit tests for FinancialSafetyGuard and TransactionSimulator."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.financial_safety_guard import (
    FinancialBudgetConfig,
    FinancialDecision,
    FinancialRiskTier,
    FinancialSafetyGuard,
    TransactionIntent,
    TransactionSimulator,
)


@pytest.fixture
def guard() -> FinancialSafetyGuard:
    config = FinancialBudgetConfig(
        single_tx_limit_usd=50.0,
        daily_limit_usd=200.0,
        max_allowed_slippage_bps=100,  # 1.0%
        critical_risk_score_threshold=80,
    )
    return FinancialSafetyGuard(config=config)


def test_clean_transaction_auto_approved(guard: FinancialSafetyGuard) -> None:
    intent = TransactionIntent(
        tx_id="tx_001",
        source_account="0x1111111111111111111111111111111111111111",
        target_contract_or_recipient="0x2222222222222222222222222222222222222222",
        asset_symbol="USDT",
        amount=20.0,
        amount_usd=20.0,
        slippage_tolerance_bps=50,
        max_fee_limit=2.0,
        payload_digest="sha256_mock_001",
    )
    card = guard.evaluate_transaction(intent)

    assert card.decision == FinancialDecision.APPROVE
    assert card.risk_tier in (FinancialRiskTier.LOW, FinancialRiskTier.MEDIUM)
    assert card.requires_manual_approval is False
    assert guard.daily_spent_usd == 20.0
    assert card.remaining_daily_budget_usd == 180.0


def test_single_tx_limit_exceeded_triggers_confirmation(guard: FinancialSafetyGuard) -> None:
    intent = TransactionIntent(
        tx_id="tx_002",
        source_account="0x1111111111111111111111111111111111111111",
        target_contract_or_recipient="0x3333333333333333333333333333333333333333",
        asset_symbol="USDC",
        amount=75.0,  # exceeds single limit 50.0
        amount_usd=75.0,
        slippage_tolerance_bps=50,
        max_fee_limit=2.0,
        payload_digest="sha256_mock_002",
    )
    card = guard.evaluate_transaction(intent)

    assert card.decision == FinancialDecision.ASK_CONFIRMATION
    assert card.requires_manual_approval is True
    assert "exceeds auto-approval limit" in (card.rejection_reason or "")
    # Spent amount should NOT accumulate before manual approval
    assert guard.daily_spent_usd == 0.0

    # Manual approval succeeds
    approved = guard.approve_manually("tx_002")
    assert approved is not None
    assert approved.decision == FinancialDecision.APPROVE
    assert guard.daily_spent_usd == 75.0


def test_slippage_breaker_triggers_rejection(guard: FinancialSafetyGuard) -> None:
    # High USD volume simulates deep market impact exceeding max_allowed_slippage_bps=100
    intent = TransactionIntent(
        tx_id="tx_003",
        source_account="0x1111111111111111111111111111111111111111",
        target_contract_or_recipient="0x4444444444444444444444444444444444444444",
        asset_symbol="SOL",
        amount=2500.0,
        amount_usd=2500.0,  # triggers market impact > 150 bps
        slippage_tolerance_bps=300,
        max_fee_limit=10.0,
        payload_digest="sha256_mock_003",
    )
    card = guard.evaluate_transaction(intent)

    assert card.decision == FinancialDecision.REJECT_BREAKER
    assert card.requires_manual_approval is False
    assert "circuit breaker triggered" in (card.rejection_reason or "")


def test_daily_budget_depletion_triggers_ask(guard: FinancialSafetyGuard) -> None:
    # First tx: 40 USD (ok)
    guard.evaluate_transaction(
        TransactionIntent(
            tx_id="tx_d1",
            source_account="0x1",
            target_contract_or_recipient="0x2",
            asset_symbol="USDT",
            amount=40.0,
            amount_usd=40.0,
            slippage_tolerance_bps=20,
            max_fee_limit=1.0,
            payload_digest="dig_1",
        )
    )
    # Second tx: 40 USD (ok)
    guard.evaluate_transaction(
        TransactionIntent(
            tx_id="tx_d2",
            source_account="0x1",
            target_contract_or_recipient="0x2",
            asset_symbol="USDT",
            amount=40.0,
            amount_usd=40.0,
            slippage_tolerance_bps=20,
            max_fee_limit=1.0,
            payload_digest="dig_2",
        )
    )
    # Third tx: 40 USD (ok)
    guard.evaluate_transaction(
        TransactionIntent(
            tx_id="tx_d3",
            source_account="0x1",
            target_contract_or_recipient="0x2",
            asset_symbol="USDT",
            amount=40.0,
            amount_usd=40.0,
            slippage_tolerance_bps=20,
            max_fee_limit=1.0,
            payload_digest="dig_3",
        )
    )
    # Fourth tx: 40 USD (ok) -> total 160 USD
    guard.evaluate_transaction(
        TransactionIntent(
            tx_id="tx_d4",
            source_account="0x1",
            target_contract_or_recipient="0x2",
            asset_symbol="USDT",
            amount=40.0,
            amount_usd=40.0,
            slippage_tolerance_bps=20,
            max_fee_limit=1.0,
            payload_digest="dig_4",
        )
    )
    assert guard.daily_spent_usd == 160.0

    # Fifth tx: 45 USD -> 160 + 45 = 205 > 200 daily limit
    card5 = guard.evaluate_transaction(
        TransactionIntent(
            tx_id="tx_d5",
            source_account="0x1",
            target_contract_or_recipient="0x2",
            asset_symbol="USDT",
            amount=45.0,
            amount_usd=45.0,
            slippage_tolerance_bps=20,
            max_fee_limit=1.0,
            payload_digest="dig_5",
        )
    )
    assert card5.decision == FinancialDecision.ASK_CONFIRMATION
    assert "exceeds remaining daily budget" in (card5.rejection_reason or "")


def test_budget_reset_and_simulator_standalone() -> None:
    simulator = TransactionSimulator()
    sim_res = simulator.simulate(
        TransactionIntent(
            tx_id="test_sim",
            source_account="0x1",
            target_contract_or_recipient="0x2",
            asset_symbol="ETH",
            amount=10.0,
            amount_usd=10.0,
            slippage_tolerance_bps=30,
            max_fee_limit=0.1,  # less than base fee -> adds risk
            payload_digest="dig_test",
        )
    )
    assert sim_res.is_simulated is True
    assert sim_res.risk_score >= 0
    assert len(sim_res.simulation_notes) >= 3
