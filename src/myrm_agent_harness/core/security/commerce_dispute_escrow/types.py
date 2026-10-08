"""Core data structures and domain types for Agent Commerce Dispute & Escrow.

[INPUT]
- Domain models representing jobs, strategy types, escrow deposits, and disputes.

[OUTPUT]
- Strongly-typed representations for escrow funds, multi-seat arbitration, and circuit breakers.

[POS]
- Harness core security contracts for autonomous commerce dispute resolution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class StrategyType(StrEnum):
    """Task strategy types supported by autonomous commerce protocol."""

    PROGRAM = "PROGRAM"
    RUBRIC = "RUBRIC"
    HYBRID = "HYBRID"
    CEX_CAPITAL = "CEX_CAPITAL"


class EscrowStatus(StrEnum):
    """Lifecycle status of an autonomous commercial escrow deposit."""

    FUNDED = "FUNDED"
    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    DISPUTED = "DISPUTED"
    RESOLVED_RELEASED = "RESOLVED_RELEASED"
    RESOLVED_REFUNDED = "RESOLVED_REFUNDED"
    FROZEN_CIRCUIT_BREAKER = "FROZEN_CIRCUIT_BREAKER"


class DisputeStatus(StrEnum):
    """Lifecycle status of a multi-seat arbitration dispute."""

    OPEN = "OPEN"
    VOTING = "VOTING"
    REVEAL = "REVEAL"
    SETTLED = "SETTLED"


class DisputeOutcome(StrEnum):
    """Arbitration final outcome decision."""

    PENDING = "PENDING"
    OVERTURNED = "OVERTURNED"  # Client wins: Deliverable rejected, escrow refunded
    UPHELD = "UPHELD"  # Provider wins: Deliverable accepted, escrow released



@dataclass(frozen=True)
class TradingCircuitBreakers:
    """Quantitative risk thresholds and circuit breaker parameters for CEX_CAPITAL."""

    max_position_pct: float = 25.0
    max_daily_loss_pct: float = 10.0
    max_open_exposure_pct: float = 50.0
    emergency_kill_switch_active: bool = False


@dataclass
class ArbitratorVote:
    """Individual vote record for a selected arbitration seat."""

    seat_index: int
    arbitrator_id: str
    commitment_hash: str | None = None
    revealed_vote: int | None = None  # 0 = Uphold provider, 1 = Overturn to client
    revealed_salt: str | None = None
    revealed_at: float | None = None


@dataclass
class EscrowAccount:
    """Escrow holding funds for an autonomous agent commerce agreement."""

    escrow_id: str
    job_id: str
    client_agent_id: str
    provider_agent_id: str
    strategy_type: StrategyType
    amount: float
    status: EscrowStatus = EscrowStatus.FUNDED
    deliverable_hash: str | None = None
    circuit_breakers: TradingCircuitBreakers | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class DisputeCase:
    """Dispute case arbitrating contested deliverable releases."""

    dispute_id: str
    escrow_id: str
    initiator_agent_id: str
    deposit_amount: float
    status: DisputeStatus = DisputeStatus.OPEN
    votes: list[ArbitratorVote] = field(default_factory=list)
    outcome: DisputeOutcome = DisputeOutcome.PENDING
    settled_at: float | None = None


@dataclass(frozen=True)
class DisputeSettlementResult:
    """Financial distribution breakdown following dispute settlement."""

    dispute_id: str
    escrow_id: str
    outcome: DisputeOutcome
    refund_to_client: float
    release_to_provider: float
    deposit_refunded: float
    arbitrator_fee_pool: float
