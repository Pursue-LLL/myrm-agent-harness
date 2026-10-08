"""Core execution engine for Agent Commerce Dispute & Escrow.

[INPUT]
- Escrow creation, deliverable submission, dispute raising, and arbitrator vote commitments.

[OUTPUT]
- Deterministic escrow state transitions, multi-seat arbitration decisions, and fund distribution.

[POS]
- Protocol engine governing commercial deliverable trust and dispute resolution.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from myrm_agent_harness.core.security.commerce_dispute_escrow.circuit_breaker import (
    CommerceCircuitBreakerEvaluator,
)
from myrm_agent_harness.core.security.commerce_dispute_escrow.types import (
    ArbitratorVote,
    DisputeCase,
    DisputeOutcome,
    DisputeSettlementResult,
    DisputeStatus,
    EscrowAccount,
    EscrowStatus,
    StrategyType,
    TradingCircuitBreakers,
)


class CommerceEscrowManager:
    """Manages autonomous agent commercial escrow accounts and arbitration lifecycles."""

    def __init__(self) -> None:
        """Initialize in-memory escrow and dispute registry."""
        self._escrows: dict[str, EscrowAccount] = {}
        self._disputes: dict[str, DisputeCase] = {}

    def create_escrow(
        self,
        job_id: str,
        client_agent_id: str,
        provider_agent_id: str,
        strategy_type: StrategyType,
        amount: float,
        circuit_breakers: TradingCircuitBreakers | None = None,
    ) -> EscrowAccount:
        """Create and fund a new commercial escrow account."""
        if amount <= 0:
            raise ValueError(f"Escrow amount must be positive, got {amount}")

        escrow_id = f"escrow_{uuid.uuid4().hex[:12]}"
        now = time.time()
        escrow = EscrowAccount(
            escrow_id=escrow_id,
            job_id=job_id,
            client_agent_id=client_agent_id,
            provider_agent_id=provider_agent_id,
            strategy_type=strategy_type,
            amount=amount,
            status=EscrowStatus.FUNDED,
            circuit_breakers=circuit_breakers,
            created_at=now,
            updated_at=now,
        )
        self._escrows[escrow_id] = escrow
        return escrow

    def get_escrow(self, escrow_id: str) -> EscrowAccount:
        """Retrieve escrow account by identifier."""
        if escrow_id not in self._escrows:
            raise KeyError(f"Escrow '{escrow_id}' not found.")
        return self._escrows[escrow_id]

    def submit_deliverable(
        self,
        escrow_id: str,
        provider_agent_id: str,
        deliverable_hash: str,
    ) -> EscrowAccount:
        """Submit on-chain/proof hash for completed work."""
        escrow = self.get_escrow(escrow_id)
        if escrow.provider_agent_id != provider_agent_id:
            raise PermissionError(
                f"Agent '{provider_agent_id}' is not the assigned provider for escrow '{escrow_id}'."
            )
        if escrow.status not in (EscrowStatus.FUNDED, EscrowStatus.IN_PROGRESS):
            raise ValueError(f"Cannot submit deliverable for escrow in state {escrow.status.value}")

        escrow.deliverable_hash = deliverable_hash
        escrow.status = EscrowStatus.DELIVERED
        escrow.updated_at = time.time()
        return escrow

    def release_funds(
        self,
        escrow_id: str,
        client_agent_id: str,
    ) -> EscrowAccount:
        """Release escrow funds to provider upon client approval."""
        escrow = self.get_escrow(escrow_id)
        if escrow.client_agent_id != client_agent_id:
            raise PermissionError(
                f"Agent '{client_agent_id}' is not the client for escrow '{escrow_id}'."
            )
        if escrow.status != EscrowStatus.DELIVERED:
            raise ValueError(f"Cannot release funds: escrow is in state {escrow.status.value}")

        escrow.status = EscrowStatus.RESOLVED_RELEASED
        escrow.updated_at = time.time()
        return escrow

    def evaluate_circuit_breaker(
        self,
        escrow_id: str,
        current_position_pct: float = 0.0,
        current_daily_loss_pct: float = 0.0,
        current_open_exposure_pct: float = 0.0,
        emergency_trigger: bool = False,
    ) -> tuple[bool, str | None]:
        """Check risk parameters and freeze escrow if limits are violated."""
        escrow = self.get_escrow(escrow_id)
        triggered, reason = CommerceCircuitBreakerEvaluator.evaluate(
            circuit_breakers=escrow.circuit_breakers,
            current_position_pct=current_position_pct,
            current_daily_loss_pct=current_daily_loss_pct,
            current_open_exposure_pct=current_open_exposure_pct,
            emergency_trigger=emergency_trigger,
        )
        if triggered:
            escrow.status = EscrowStatus.FROZEN_CIRCUIT_BREAKER
            escrow.updated_at = time.time()
        return triggered, reason

    def raise_dispute(
        self,
        escrow_id: str,
        initiator_agent_id: str,
        deposit_amount: float | None = None,
        arbitrators: list[str] | None = None,
    ) -> DisputeCase:
        """Initiate multi-seat arbitration against deliverable or release."""
        escrow = self.get_escrow(escrow_id)
        if initiator_agent_id not in (escrow.client_agent_id, escrow.provider_agent_id):
            raise PermissionError(f"Unauthorized initiator '{initiator_agent_id}' for escrow.")
        if escrow.status in (
            EscrowStatus.RESOLVED_RELEASED,
            EscrowStatus.RESOLVED_REFUNDED,
            EscrowStatus.DISPUTED,
        ):
            raise ValueError(f"Cannot raise dispute on escrow in status {escrow.status.value}")

        min_deposit = max(5.0, escrow.amount * 0.05)
        effective_deposit = deposit_amount if deposit_amount is not None else min_deposit
        if effective_deposit < min_deposit:
            raise ValueError(
                f"Deposit {effective_deposit:.2f} is below minimum requirement {min_deposit:.2f}"
            )

        arb_list = arbitrators or ["arbitrator_seat_0", "arbitrator_seat_1", "arbitrator_seat_2"]
        if len(arb_list) != 3:
            raise ValueError(f"Arbitration requires exactly 3 arbitrator seats, got {len(arb_list)}")

        dispute_id = f"disp_{uuid.uuid4().hex[:12]}"
        votes = [
            ArbitratorVote(seat_index=idx, arbitrator_id=arb_id)
            for idx, arb_id in enumerate(arb_list)
        ]
        dispute = DisputeCase(
            dispute_id=dispute_id,
            escrow_id=escrow_id,
            initiator_agent_id=initiator_agent_id,
            deposit_amount=effective_deposit,
            status=DisputeStatus.VOTING,
            votes=votes,
            outcome=DisputeOutcome.PENDING,
        )
        self._disputes[dispute_id] = dispute
        escrow.status = EscrowStatus.DISPUTED
        escrow.updated_at = time.time()
        return dispute

    def get_dispute(self, dispute_id: str) -> DisputeCase:
        """Retrieve dispute case by identifier."""
        if dispute_id not in self._disputes:
            raise KeyError(f"Dispute '{dispute_id}' not found.")
        return self._disputes[dispute_id]

    def commit_vote(
        self,
        dispute_id: str,
        seat_index: int,
        arbitrator_id: str,
        commitment_hash: str,
    ) -> DisputeCase:
        """Submit cryptographic commitment for arbitrator vote."""
        dispute = self.get_dispute(dispute_id)
        if dispute.status != DisputeStatus.VOTING:
            raise ValueError(f"Cannot commit vote in dispute status {dispute.status.value}")
        if seat_index < 0 or seat_index >= len(dispute.votes):
            raise IndexError(f"Invalid seat index {seat_index}")

        seat = dispute.votes[seat_index]
        if seat.arbitrator_id != arbitrator_id:
            raise PermissionError(f"Arbitrator ID mismatch for seat {seat_index}")

        seat.commitment_hash = commitment_hash
        # If all seats committed, transition to REVEAL
        if all(v.commitment_hash is not None for v in dispute.votes):
            dispute.status = DisputeStatus.REVEAL

        return dispute

    def reveal_vote(
        self,
        dispute_id: str,
        seat_index: int,
        arbitrator_id: str,
        vote: int,
        salt: str,
    ) -> DisputeCase:
        """Reveal committed arbitrator vote with salt verification."""
        dispute = self.get_dispute(dispute_id)
        if dispute.status != DisputeStatus.REVEAL:
            raise ValueError(f"Cannot reveal vote in dispute status {dispute.status.value}")
        if seat_index < 0 or seat_index >= len(dispute.votes):
            raise IndexError(f"Invalid seat index {seat_index}")
        if vote not in (0, 1):
            raise ValueError(f"Vote must be 0 (uphold) or 1 (overturn), got {vote}")

        seat = dispute.votes[seat_index]
        if seat.arbitrator_id != arbitrator_id:
            raise PermissionError(f"Arbitrator ID mismatch for seat {seat_index}")
        if not seat.commitment_hash:
            raise ValueError("No commitment registered for this seat.")

        expected_hash = hashlib.sha256(f"{vote}:{salt}".encode()).hexdigest()
        if expected_hash != seat.commitment_hash:
            raise ValueError("Commitment hash mismatch on revealed vote and salt.")

        seat.revealed_vote = vote
        seat.revealed_salt = salt
        seat.revealed_at = time.time()
        return dispute

    def settle_dispute(
        self,
        dispute_id: str,
    ) -> tuple[DisputeCase, EscrowAccount, DisputeSettlementResult]:
        """Tally revealed votes and execute financial settlement."""
        dispute = self.get_dispute(dispute_id)
        escrow = self.get_escrow(dispute.escrow_id)
        revealed_votes = [v.revealed_vote for v in dispute.votes if v.revealed_vote is not None]
        if len(revealed_votes) < 2:
            raise ValueError(f"Insufficient revealed votes ({len(revealed_votes)}/3) to settle.")

        overturn_count = sum(1 for v in revealed_votes if v == 1)
        is_overturned = overturn_count >= 2

        if is_overturned:
            outcome = DisputeOutcome.OVERTURNED
            escrow.status = EscrowStatus.RESOLVED_REFUNDED
            refund_to_client = escrow.amount + (dispute.deposit_amount * 0.7)
            release_to_provider = 0.0
            deposit_refunded = dispute.deposit_amount * 0.7
            fee_pool = dispute.deposit_amount * 0.3
        else:
            outcome = DisputeOutcome.UPHELD
            escrow.status = EscrowStatus.RESOLVED_RELEASED
            refund_to_client = 0.0
            release_to_provider = escrow.amount
            deposit_refunded = 0.0
            fee_pool = dispute.deposit_amount * 0.3

        dispute.outcome = outcome
        dispute.status = DisputeStatus.SETTLED
        dispute.settled_at = time.time()
        escrow.updated_at = time.time()

        settlement = DisputeSettlementResult(
            dispute_id=dispute_id,
            escrow_id=escrow.escrow_id,
            outcome=outcome,
            refund_to_client=refund_to_client,
            release_to_provider=release_to_provider,
            deposit_refunded=deposit_refunded,
            arbitrator_fee_pool=fee_pool,
        )
        return dispute, escrow, settlement
