"""Unit tests for Durable Session Owner Fencing and Admission Control Suite.

Validates monotonic epoch bump on takeover, admission gate fence rejection,
quiescence storage-busy rejection, and lease release semantics.
"""

from __future__ import annotations

import time

from myrm_agent_harness.agent.context_management.owner_fencing import (
    AdmissionStatus,
    DurableSessionOwnerFencer,
    FencingConfig,
)


def test_initial_lease_acquisition_and_turn_admission() -> None:
    """Verifies first-time lease acquisition initializes epoch 1 and admits valid turns."""
    fencer = DurableSessionOwnerFencer()
    session_id = "session-fenced-001"
    client_a = "client-web-tab-1"

    lease = fencer.acquire_or_takeover_lease(session_id, client_a)
    assert lease.session_id == session_id
    assert lease.client_id == client_a
    assert lease.epoch == 1
    assert lease.lease_token.startswith("lease-ep1-")
    assert fencer.get_current_epoch(session_id) == 1

    # Valid turn admission
    decision = fencer.admit_turn(
        session_id=session_id,
        client_id=client_a,
        lease_token=lease.lease_token,
        requested_epoch=1,
    )
    assert decision.status == AdmissionStatus.ADMITTED
    assert decision.allowed is True
    assert decision.current_epoch == 1

    # Same client renewing lease retains epoch
    renewed = fencer.acquire_or_takeover_lease(session_id, client_a)
    assert renewed.epoch == 1
    assert renewed.lease_token == lease.lease_token


def test_client_takeover_bumps_epoch_and_fences_stale_client() -> None:
    """Verifies client takeover increments epoch and fences previous client from double-writing."""
    fencer = DurableSessionOwnerFencer()
    session_id = "session-fenced-002"
    client_a = "client-web-tab-1"
    client_b = "client-desktop-app"

    # Client A gets initial lease
    lease_a = fencer.acquire_or_takeover_lease(session_id, client_a)
    assert lease_a.epoch == 1

    # Client B takes over the session
    lease_b = fencer.acquire_or_takeover_lease(session_id, client_b)
    assert lease_b.epoch == 2
    assert lease_b.client_id == client_b
    assert lease_b.lease_token != lease_a.lease_token
    assert fencer.get_current_epoch(session_id) == 2

    # Stale Client A tries to inject turn using old lease token -> Fenced!
    decision_stale = fencer.admit_turn(
        session_id=session_id,
        client_id=client_a,
        lease_token=lease_a.lease_token,
        requested_epoch=1,
    )
    assert decision_stale.status == AdmissionStatus.FENCED_REJECTED
    assert decision_stale.allowed is False
    assert decision_stale.current_epoch == 2
    assert "fenced" in decision_stale.reason.lower()

    # Active Client B turn injection succeeds
    decision_active = fencer.admit_turn(
        session_id=session_id,
        client_id=client_b,
        lease_token=lease_b.lease_token,
        requested_epoch=2,
    )
    assert decision_active.status == AdmissionStatus.ADMITTED
    assert decision_active.allowed is True


def test_quiescing_session_rejects_with_storage_busy() -> None:
    """Verifies that maintenance quiescence rejects turn admission with STORAGE_BUSY."""
    fencer = DurableSessionOwnerFencer()
    session_id = "session-fenced-003"
    client_a = "client-runner"

    lease = fencer.acquire_or_takeover_lease(session_id, client_a)

    # Place session in quiescence
    fencer.quiesce_session(session_id)

    decision_busy = fencer.admit_turn(
        session_id=session_id,
        client_id=client_a,
        lease_token=lease.lease_token,
    )
    assert decision_busy.status == AdmissionStatus.STORAGE_BUSY
    assert decision_busy.allowed is False
    assert "storage busy" in decision_busy.reason.lower()

    # Resume session
    fencer.resume_session(session_id)
    decision_resumed = fencer.admit_turn(
        session_id=session_id,
        client_id=client_a,
        lease_token=lease.lease_token,
    )
    assert decision_resumed.status == AdmissionStatus.ADMITTED
    assert decision_resumed.allowed is True


def test_lease_expiration_and_explicit_release() -> None:
    """Verifies expired lease rejection and explicit release semantics."""
    # Config with short TTL for test
    cfg = FencingConfig(lease_ttl_seconds=0.05)
    fencer = DurableSessionOwnerFencer(config=cfg)
    session_id = "session-fenced-004"
    client_id = "client-ephemeral"

    lease = fencer.acquire_or_takeover_lease(session_id, client_id)

    # Allow lease to expire
    time.sleep(0.08)

    decision_expired = fencer.admit_turn(
        session_id=session_id,
        client_id=client_id,
        lease_token=lease.lease_token,
    )
    assert decision_expired.status == AdmissionStatus.INVALID_LEASE
    assert decision_expired.allowed is False
    assert "expired" in decision_expired.reason.lower()

    # Re-acquire and release explicitly
    new_lease = fencer.acquire_or_takeover_lease(session_id, client_id)
    assert fencer.get_active_lease(session_id) is not None

    released = fencer.release_lease(session_id, client_id, new_lease.lease_token)
    assert released is True
    assert fencer.get_active_lease(session_id) is None

    # After release, turn is rejected as invalid lease
    decision_after_release = fencer.admit_turn(
        session_id=session_id,
        client_id=client_id,
        lease_token=new_lease.lease_token,
    )
    assert decision_after_release.status == AdmissionStatus.INVALID_LEASE
    assert decision_after_release.allowed is False
