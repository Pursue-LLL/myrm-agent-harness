"""
[POS] src/myrm_agent_harness/core/security/agentic_commerce/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] PaymentRailEnum, CommerceTransactionStatus, MerchantSpec, PaymentIntent, EphemeralPaymentToken, FinancialBudgetPolicy, SettlementReceipt, AgenticCommerceMetrics

Data structures and specifications for Autonomous Agent Commerce Protocol & Zero-Knowledge Financial Vault Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PaymentRailEnum(StrEnum):
    """Payment settlement rails supported by the agentic commerce protocol."""

    STRIPE_AGENT_VIRTUAL_CARD = "STRIPE_AGENT_VIRTUAL_CARD"
    PAYPAL_COMMERCE = "PAYPAL_COMMERCE"
    VISA_VIRTUAL_ACCOUNT = "VISA_VIRTUAL_ACCOUNT"
    MOCK_SANDBOX = "MOCK_SANDBOX"


class CommerceTransactionStatus(StrEnum):
    """Lifecycle status of an agentic purchase or subscription transaction."""

    DRAFT_INTENT = "DRAFT_INTENT"
    AUTO_APPROVED = "AUTO_APPROVED"
    PENDING_HITL_CONFIRMATION = "PENDING_HITL_CONFIRMATION"
    SETTLED = "SETTLED"
    REJECTED_BUDGET_EXCEEDED = "REJECTED_BUDGET_EXCEEDED"
    REJECTED_USER_DENIED = "REJECTED_USER_DENIED"


@dataclass(frozen=True)
class MerchantSpec:
    """Descriptor of a merchant or digital vendor evaluated for commerce."""

    merchant_id: str
    merchant_name: str
    domain: str
    category: str
    is_whitelisted: bool = True


@dataclass(frozen=True)
class PaymentIntent:
    """Structured payment intent generated autonomously by agent in sandbox."""

    intent_id: str
    merchant: MerchantSpec
    amount_cents: int
    currency: str
    line_items: tuple[str, ...]
    payment_rail: PaymentRailEnum
    created_at: float


@dataclass(frozen=True)
class EphemeralPaymentToken:
    """Single-use ephemeral payment token minted by zero-knowledge financial vault."""

    token_id: str
    intent_id: str
    masked_card_last4: str
    token_string: str
    max_amount_cents: int
    expires_at: float
    is_consumed: bool = False


@dataclass(frozen=True)
class FinancialBudgetPolicy:
    """Enforceable multi-tier spend guardrails and hard caps."""

    daily_hard_cap_cents: int = 5000  # $50.00
    single_transaction_max_cents: int = 2000  # $20.00
    auto_approval_threshold_cents: int = 500  # $5.00
    allowed_categories: tuple[str, ...] = (
        "cloud_compute",
        "api_credits",
        "e_books",
        "development_tools",
        "general_subscription",
    )


@dataclass(frozen=True)
class SettlementReceipt:
    """Immutable ledger receipt generated upon completed financial settlement."""

    receipt_id: str
    intent_id: str
    status: CommerceTransactionStatus
    amount_cents: int
    currency: str
    merchant_name: str
    payment_rail: PaymentRailEnum
    confirmation_code: str
    settled_at: float


@dataclass
class AgenticCommerceMetrics:
    """Cumulative operational metrics for agentic commerce operations."""

    intents_created_total: int = 0
    auto_approved_total: int = 0
    hitl_approvals_requested_total: int = 0
    hitl_approved_total: int = 0
    hitl_denied_total: int = 0
    budget_rejections_total: int = 0
    settlements_completed_total: int = 0
    tokens_minted_total: int = 0
    total_spent_cents: int = 0
