"""
[POS] tests/unit/test_agentic_commerce_suite.py
[INPUT] pytest, typing
[OUTPUT] Comprehensive unit tests for Autonomous Agent Commerce Protocol & Zero-Knowledge Financial Vault Suite

Validates zero-knowledge token lifecycle, spend guardrails, HITL gating, and final settlement receipts.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.agentic_commerce import (
    AgenticCommerceSuite,
    CommerceTransactionStatus,
    FinancialBudgetPolicy,
    FinancialSpendGuardrail,
    MerchantSpec,
    PaymentIntent,
    PaymentRailEnum,
    ZeroKnowledgeFinancialVault,
)


def test_zero_knowledge_vault_token_lifecycle() -> None:
    """Validate ephemeral token minting, single-use consumption, and replay protection."""
    vault = ZeroKnowledgeFinancialVault(masked_card_last4="9988")
    assert vault.masked_card_last4 == "9988"

    token = vault.mint_ephemeral_token(
        intent_id="intent-test-1",
        max_amount_cents=1500,
    )
    assert token.token_id.startswith("tok-")
    assert token.token_string.startswith("ephem_sec_")
    assert token.masked_card_last4 == "9988"
    assert not token.is_consumed

    # Valid consumption
    consumed = vault.validate_and_consume_token(token.token_string, charge_amount_cents=1200)
    assert consumed.is_consumed is True

    # Replay must fail
    with pytest.raises(ValueError, match="already been consumed"):
        vault.validate_and_consume_token(token.token_string, charge_amount_cents=1200)


def test_zero_knowledge_vault_overcharge_blocked() -> None:
    """Validate that attempting to charge more than token authorized cap is blocked."""
    vault = ZeroKnowledgeFinancialVault()
    token = vault.mint_ephemeral_token(
        intent_id="intent-test-2",
        max_amount_cents=500,
    )

    with pytest.raises(ValueError, match="exceeds token authorized cap"):
        vault.validate_and_consume_token(token.token_string, charge_amount_cents=600)


def test_spend_guardrail_budget_tiers() -> None:
    """Validate auto-approval vs HITL gating vs hard budget rejections."""
    policy = FinancialBudgetPolicy(
        daily_hard_cap_cents=5000,  # $50.00
        single_transaction_max_cents=2000,  # $20.00
        auto_approval_threshold_cents=300,  # $3.00
        allowed_categories=("cloud_compute", "api_credits"),
    )
    guard = FinancialSpendGuardrail(policy=policy)

    merchant = MerchantSpec(
        merchant_id="m-1",
        merchant_name="CloudProvider",
        domain="cloud.example.com",
        category="cloud_compute",
        is_whitelisted=True,
    )

    # 1. Under auto threshold -> AUTO_APPROVED
    intent_auto = PaymentIntent(
        intent_id="pi-1",
        merchant=merchant,
        amount_cents=250,
        currency="USD",
        line_items=("1h spot instance",),
        payment_rail=PaymentRailEnum.STRIPE_AGENT_VIRTUAL_CARD,
        created_at=1000.0,
    )
    status_auto, _ = guard.evaluate_intent(intent_auto)
    assert status_auto == CommerceTransactionStatus.AUTO_APPROVED

    # 2. Over auto threshold but within budget -> PENDING_HITL_CONFIRMATION
    intent_hitl = PaymentIntent(
        intent_id="pi-2",
        merchant=merchant,
        amount_cents=1500,
        currency="USD",
        line_items=("Monthly database",),
        payment_rail=PaymentRailEnum.STRIPE_AGENT_VIRTUAL_CARD,
        created_at=1000.0,
    )
    status_hitl, _ = guard.evaluate_intent(intent_hitl)
    assert status_hitl == CommerceTransactionStatus.PENDING_HITL_CONFIRMATION

    # 3. Exceeds single transaction cap ($20.00) -> REJECTED_BUDGET_EXCEEDED
    intent_over_single = PaymentIntent(
        intent_id="pi-3",
        merchant=merchant,
        amount_cents=2500,
        currency="USD",
        line_items=("Enterprise plan",),
        payment_rail=PaymentRailEnum.STRIPE_AGENT_VIRTUAL_CARD,
        created_at=1000.0,
    )
    status_single, _ = guard.evaluate_intent(intent_over_single)
    assert status_single == CommerceTransactionStatus.REJECTED_BUDGET_EXCEEDED

    # 4. Forbidden category -> REJECTED_BUDGET_EXCEEDED
    bad_merchant = MerchantSpec(
        merchant_id="m-bad",
        merchant_name="CasinoGame",
        domain="gamble.example.com",
        category="gambling",
    )
    intent_bad_cat = PaymentIntent(
        intent_id="pi-4",
        merchant=bad_merchant,
        amount_cents=100,
        currency="USD",
        line_items=("Chips",),
        payment_rail=PaymentRailEnum.STRIPE_AGENT_VIRTUAL_CARD,
        created_at=1000.0,
    )
    status_bad, _ = guard.evaluate_intent(intent_bad_cat)
    assert status_bad == CommerceTransactionStatus.REJECTED_BUDGET_EXCEEDED


def test_agentic_commerce_suite_end_to_end_auto_settlement() -> None:
    """Validate micro-purchase auto-approval and instantaneous settlement via suite facade."""
    suite = AgenticCommerceSuite()
    merchant = MerchantSpec(
        merchant_id="m-api",
        merchant_name="FastInferenceAPI",
        domain="api.inference.com",
        category="api_credits",
    )

    # Create intent for $3.50 (under default $5.00 auto-threshold)
    intent, status, _, token = suite.create_payment_intent(
        merchant=merchant,
        amount_cents=350,
        currency="USD",
        line_items=("1M tokens",),
    )

    assert status == CommerceTransactionStatus.AUTO_APPROVED
    assert token is not None

    # Settle transaction
    receipt = suite.settle_transaction(token.token_string, intent)
    assert receipt.status == CommerceTransactionStatus.SETTLED
    assert receipt.amount_cents == 350
    assert receipt.confirmation_code.startswith("AUTH_")

    budget_status = suite.get_budget_status()
    assert budget_status["daily_spent_cents"] == 350
    assert budget_status["remaining_budget_cents"] == budget_status["daily_hard_cap_cents"] - 350


def test_agentic_commerce_suite_hitl_approval_and_rejection() -> None:
    """Validate high-value purchase HITL confirmation and rejection flow."""
    suite = AgenticCommerceSuite()
    merchant = MerchantSpec(
        merchant_id="m-cloud",
        merchant_name="ComputeCloud",
        domain="compute.com",
        category="cloud_compute",
    )

    # 1. Create intent for $12.00 (exceeds $5.00 auto-threshold)
    intent, status, _, token = suite.create_payment_intent(
        merchant=merchant,
        amount_cents=1200,
        currency="USD",
    )
    assert status == CommerceTransactionStatus.PENDING_HITL_CONFIRMATION
    assert token is None

    # 2. Confirm HITL
    approved_intent, minted_token = suite.confirm_hitl_and_mint(intent.intent_id)
    assert approved_intent.intent_id == intent.intent_id
    assert minted_token is not None

    # 3. Settle
    receipt = suite.settle_transaction(minted_token.token_string, approved_intent)
    assert receipt.status == CommerceTransactionStatus.SETTLED

    # 4. Deny flow
    intent2, _, _, _ = suite.create_payment_intent(
        merchant=merchant,
        amount_cents=1500,
        currency="USD",
    )
    denied = suite.deny_hitl(intent2.intent_id)
    assert denied.intent_id == intent2.intent_id

    metrics = suite.metrics
    assert metrics.intents_created_total == 2
    assert metrics.hitl_approvals_requested_total == 2
    assert metrics.hitl_approved_total == 1
    assert metrics.hitl_denied_total == 1
    assert metrics.settlements_completed_total == 1
    assert metrics.total_spent_cents == 1200
