"""Type definitions for Autonomous Financial Execution Safety Guard and Simulation Suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class FinancialRiskTier(StrEnum):
    """Categorization of transaction risk exposure."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FinancialDecision(StrEnum):
    """Execution decision determined by pre-flight checks and budget governors."""

    APPROVE = "APPROVE"
    ASK_CONFIRMATION = "ASK_CONFIRMATION"
    REJECT_BREAKER = "REJECT_BREAKER"


@dataclass(slots=True, frozen=True)
class TransactionIntent:
    """Pre-flight deterministic semantic intent of a financial or market order."""

    tx_id: str
    source_account: str
    target_contract_or_recipient: str
    asset_symbol: str
    amount: float
    amount_usd: float
    slippage_tolerance_bps: int  # 1 bps = 0.01%, 150 bps = 1.5%
    max_fee_limit: float
    payload_digest: str


@dataclass(slots=True, frozen=True)
class TransactionSimulationResult:
    """Outcome of sandbox dry-run execution simulation."""

    is_simulated: bool
    estimated_gas_or_fee: float
    estimated_slippage_bps: int
    max_loss_usd: float
    risk_score: int  # 0 to 100
    simulation_notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FinancialBudgetConfig:
    """Strict spending limits and slippage tolerance thresholds."""

    single_tx_limit_usd: float = 100.0
    daily_limit_usd: float = 500.0
    max_allowed_slippage_bps: int = 150  # 1.5%
    critical_risk_score_threshold: int = 80


@dataclass(slots=True, frozen=True)
class TransactionSecurityCard:
    """Audit dossier and UI display card for transaction verification."""

    tx_id: str
    decision: FinancialDecision
    risk_tier: FinancialRiskTier
    intent: TransactionIntent
    simulation: TransactionSimulationResult
    daily_spent_usd: float
    remaining_daily_budget_usd: float
    requires_manual_approval: bool
    rejection_reason: str | None = None
    created_at: float = 0.0
