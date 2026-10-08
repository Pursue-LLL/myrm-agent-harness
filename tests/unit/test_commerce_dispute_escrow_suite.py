"""Unit tests for Agent Commerce Dispute & Escrow Suite in myrm-agent-harness."""

from __future__ import annotations

import hashlib

import pytest

from myrm_agent_harness.core.security.commerce_dispute_escrow import (
    CommerceEscrowManager,
    DisputeOutcome,
    DisputeStatus,
    EscrowStatus,
    StrategyType,
    TradingCircuitBreakers,
)


@pytest.fixture
def manager() -> CommerceEscrowManager:
    return CommerceEscrowManager()


def test_escrow_lifecycle_happy_path(manager: CommerceEscrowManager) -> None:
    # 1. Create escrow
    escrow = manager.create_escrow(
        job_id="job_001",
        client_agent_id="client_agent_alpha",
        provider_agent_id="provider_agent_beta",
        strategy_type=StrategyType.PROGRAM,
        amount=500.0,
    )
    assert escrow.status == EscrowStatus.FUNDED
    assert escrow.amount == 500.0

    # 2. Submit deliverable
    updated = manager.submit_deliverable(
        escrow_id=escrow.escrow_id,
        provider_agent_id="provider_agent_beta",
        deliverable_hash="0xabcdef1234567890",
    )
    assert updated.status == EscrowStatus.DELIVERED
    assert updated.deliverable_hash == "0xabcdef1234567890"

    # 3. Release funds
    released = manager.release_funds(
        escrow_id=escrow.escrow_id,
        client_agent_id="client_agent_alpha",
    )
    assert released.status == EscrowStatus.RESOLVED_RELEASED


def test_circuit_breaker_triggers(manager: CommerceEscrowManager) -> None:
    breakers = TradingCircuitBreakers(
        max_position_pct=20.0,
        max_daily_loss_pct=5.0,
        max_open_exposure_pct=40.0,
        emergency_kill_switch_active=False,
    )
    escrow = manager.create_escrow(
        job_id="job_cex_01",
        client_agent_id="client_trader",
        provider_agent_id="bot_trader",
        strategy_type=StrategyType.CEX_CAPITAL,
        amount=10000.0,
        circuit_breakers=breakers,
    )

    # Safe metrics
    triggered, reason = manager.evaluate_circuit_breaker(
        escrow_id=escrow.escrow_id,
        current_position_pct=15.0,
        current_daily_loss_pct=2.0,
        current_open_exposure_pct=30.0,
    )
    assert triggered is False
    assert reason is None
    assert escrow.status == EscrowStatus.FUNDED

    # Exceeding position limit
    triggered, reason = manager.evaluate_circuit_breaker(
        escrow_id=escrow.escrow_id,
        current_position_pct=25.0,
    )
    assert triggered is True
    assert "Position limit breached" in str(reason)
    assert escrow.status == EscrowStatus.FROZEN_CIRCUIT_BREAKER


def test_dispute_arbitration_overturn_client_wins(manager: CommerceEscrowManager) -> None:
    escrow = manager.create_escrow(
        job_id="job_rubric_01",
        client_agent_id="client_alice",
        provider_agent_id="provider_bob",
        strategy_type=StrategyType.RUBRIC,
        amount=1000.0,
    )
    manager.submit_deliverable(
        escrow_id=escrow.escrow_id,
        provider_agent_id="provider_bob",
        deliverable_hash="0xproof999",
    )

    # Raise dispute (min deposit is 50.0)
    dispute = manager.raise_dispute(
        escrow_id=escrow.escrow_id,
        initiator_agent_id="client_alice",
        deposit_amount=50.0,
        arbitrators=["arb_1", "arb_2", "arb_3"],
    )
    assert dispute.status == DisputeStatus.VOTING
    assert escrow.status == EscrowStatus.DISPUTED

    # Commit votes: seat 0 (vote=1), seat 1 (vote=1), seat 2 (vote=0)
    salt_0 = "salt_alice_wins_0"
    salt_1 = "salt_alice_wins_1"
    salt_2 = "salt_bob_wins_2"

    hash_0 = hashlib.sha256(f"1:{salt_0}".encode()).hexdigest()
    hash_1 = hashlib.sha256(f"1:{salt_1}".encode()).hexdigest()
    hash_2 = hashlib.sha256(f"0:{salt_2}".encode()).hexdigest()

    manager.commit_vote(dispute.dispute_id, 0, "arb_1", hash_0)
    manager.commit_vote(dispute.dispute_id, 1, "arb_2", hash_1)
    disp_reveal = manager.commit_vote(dispute.dispute_id, 2, "arb_3", hash_2)
    assert disp_reveal.status == DisputeStatus.REVEAL

    # Reveal votes
    manager.reveal_vote(dispute.dispute_id, 0, "arb_1", 1, salt_0)
    manager.reveal_vote(dispute.dispute_id, 1, "arb_2", 1, salt_1)
    manager.reveal_vote(dispute.dispute_id, 2, "arb_3", 0, salt_2)

    # Settle
    disp_settled, esc_settled, settlement = manager.settle_dispute(dispute.dispute_id)
    assert disp_settled.status == DisputeStatus.SETTLED
    assert disp_settled.outcome == DisputeOutcome.OVERTURNED
    assert esc_settled.status == EscrowStatus.RESOLVED_REFUNDED
    assert settlement.refund_to_client == 1000.0 + (50.0 * 0.7)
    assert settlement.release_to_provider == 0.0
    assert settlement.arbitrator_fee_pool == 50.0 * 0.3


def test_dispute_arbitration_uphold_provider_wins(manager: CommerceEscrowManager) -> None:
    escrow = manager.create_escrow(
        job_id="job_hybrid_02",
        client_agent_id="client_alice",
        provider_agent_id="provider_bob",
        strategy_type=StrategyType.HYBRID,
        amount=2000.0,
    )
    manager.submit_deliverable(
        escrow_id=escrow.escrow_id,
        provider_agent_id="provider_bob",
        deliverable_hash="0xproof123",
    )

    dispute = manager.raise_dispute(
        escrow_id=escrow.escrow_id,
        initiator_agent_id="client_alice",
        deposit_amount=100.0,
        arbitrators=["arb_1", "arb_2", "arb_3"],
    )

    # Uphold: seat 0 (vote=0), seat 1 (vote=0), seat 2 (vote=1)
    salt_0, salt_1, salt_2 = "s0", "s1", "s2"
    hash_0 = hashlib.sha256(f"0:{salt_0}".encode()).hexdigest()
    hash_1 = hashlib.sha256(f"0:{salt_1}".encode()).hexdigest()
    hash_2 = hashlib.sha256(f"1:{salt_2}".encode()).hexdigest()

    manager.commit_vote(dispute.dispute_id, 0, "arb_1", hash_0)
    manager.commit_vote(dispute.dispute_id, 1, "arb_2", hash_1)
    manager.commit_vote(dispute.dispute_id, 2, "arb_3", hash_2)

    manager.reveal_vote(dispute.dispute_id, 0, "arb_1", 0, salt_0)
    manager.reveal_vote(dispute.dispute_id, 1, "arb_2", 0, salt_1)
    manager.reveal_vote(dispute.dispute_id, 2, "arb_3", 1, salt_2)

    disp_settled, esc_settled, settlement = manager.settle_dispute(dispute.dispute_id)
    assert disp_settled.outcome == DisputeOutcome.UPHELD
    assert esc_settled.status == EscrowStatus.RESOLVED_RELEASED
    assert settlement.refund_to_client == 0.0
    assert settlement.release_to_provider == 2000.0
    assert settlement.arbitrator_fee_pool == 100.0 * 0.3


def test_invalid_operations_raise_errors(manager: CommerceEscrowManager) -> None:
    escrow = manager.create_escrow(
        job_id="job_err",
        client_agent_id="c1",
        provider_agent_id="p1",
        strategy_type=StrategyType.PROGRAM,
        amount=100.0,
    )

    # Non-assigned provider deliverable
    with pytest.raises(PermissionError):
        manager.submit_deliverable(escrow.escrow_id, "intruder", "0xhash")

    # Non-client fund release
    with pytest.raises(PermissionError):
        manager.release_funds(escrow.escrow_id, "intruder")

    # Deposit below minimum
    with pytest.raises(ValueError, match="below minimum requirement"):
        manager.raise_dispute(escrow.escrow_id, "c1", deposit_amount=1.0)
