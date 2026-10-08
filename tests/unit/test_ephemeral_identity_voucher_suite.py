"""
[POS] tests/unit/test_ephemeral_identity_voucher_suite.py
[INPUT] myrm_agent_harness.core.security.ephemeral_identity_voucher
[OUTPUT] Unit tests for Dynamic Ephemeral Identity & Verifiable Audit Trail Suite

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.ephemeral_identity_voucher import (
    AuditEventRecord,
    AuditPhase,
    AuditProofBundle,
    EphemeralIdentity,
    EphemeralIdentityAndVoucherFacade,
    IdentityStatus,
    MerchantLockedVoucher,
    VoucherStatus,
)


def test_ephemeral_identity_lifecycle() -> None:
    """Test identity issuance, scope check, token validation, and revocation."""
    facade = EphemeralIdentityAndVoucherFacade()

    # Issue an identity with scopes
    identity: EphemeralIdentity = facade.issue_ephemeral_identity(
        agent_id="agent-shopper-001",
        task_id="task-order-9821",
        allowed_scopes=("order.read", "checkout.execute"),
        ttl_seconds=300.0,
        metadata={"client_ip": "10.0.4.12"},
    )
    assert identity.status == IdentityStatus.ACTIVE
    assert "checkout.execute" in identity.allowed_scopes

    # Valid check
    is_valid, status, reason = facade.verify_ephemeral_identity(
        identity_id=identity.identity_id,
        token=identity.ephemeral_token,
        required_scope="checkout.execute",
    )
    assert is_valid is True
    assert status == IdentityStatus.ACTIVE

    # Invalid token check
    is_valid, status, reason = facade.verify_ephemeral_identity(
        identity_id=identity.identity_id,
        token="invalid-token-xyz",
    )
    assert is_valid is False
    assert "mismatch" in reason

    # Scope unauthorized check
    is_valid, status, reason = facade.verify_ephemeral_identity(
        identity_id=identity.identity_id,
        token=identity.ephemeral_token,
        required_scope="admin.transfer",
    )
    assert is_valid is False
    assert "not authorized" in reason

    # Explicit revocation
    revoked = facade.revoke_ephemeral_identity(
        identity_id=identity.identity_id, reason="User cancelled session"
    )
    assert revoked is True

    # Re-verify revoked identity
    is_valid, status, reason = facade.verify_ephemeral_identity(
        identity_id=identity.identity_id,
        token=identity.ephemeral_token,
    )
    assert is_valid is False
    assert status == IdentityStatus.REVOKED


def test_ephemeral_identity_ttl_expiration() -> None:
    """Test auto-expiration on short TTL."""
    facade = EphemeralIdentityAndVoucherFacade()

    # Issue with short TTL (1 second)
    identity: EphemeralIdentity = facade.issue_ephemeral_identity(
        agent_id="agent-002",
        task_id="task-quick-1",
        allowed_scopes=("test.scope",),
        ttl_seconds=1.0,
    )
    time.sleep(1.1)

    is_valid, status, reason = facade.verify_ephemeral_identity(
        identity_id=identity.identity_id,
        token=identity.ephemeral_token,
    )
    assert is_valid is False
    assert status == IdentityStatus.EXPIRED
    assert "expired" in reason.lower()


def test_merchant_locked_voucher_enforcement() -> None:
    """Test merchant domain boundary lock, monetary cap enforcement, and replay prevention."""
    facade = EphemeralIdentityAndVoucherFacade()

    # 1. Issue voucher locked to api.aws.amazon.com, capped at 150.0 USD
    voucher: MerchantLockedVoucher = facade.issue_merchant_voucher(
        identity_id="eph-id-test-1",
        target_merchant_domain="https://api.aws.amazon.com/v1/billing",
        max_authorized_amount=150.0,
        currency="USD",
        ttl_seconds=300.0,
    )
    assert voucher.target_merchant_domain == "api.aws.amazon.com"
    assert voucher.status == VoucherStatus.ISSUED

    # 2. Test domain mismatch violation (attempt to redeem on malicious phishing domain)
    success, status, reason, updated_v = facade.redeem_merchant_voucher(
        voucher_id=voucher.voucher_id,
        single_use_token=voucher.single_use_token,
        request_domain="attacker.fakepay.com",
        requested_amount=50.0,
        order_ref="ORD-001",
    )
    assert success is False
    assert status == VoucherStatus.DOMAIN_MISMATCH
    assert "violation" in reason.lower()

    # 3. Test monetary cap breach (requesting 200.0 USD against 150.0 max)
    # Issue a fresh voucher for the test
    voucher2 = facade.issue_merchant_voucher(
        identity_id="eph-id-test-1",
        target_merchant_domain="api.aws.amazon.com",
        max_authorized_amount=150.0,
        currency="USD",
    )
    success, status, reason, updated_v = facade.redeem_merchant_voucher(
        voucher_id=voucher2.voucher_id,
        single_use_token=voucher2.single_use_token,
        request_domain="api.aws.amazon.com",
        requested_amount=200.0,
        order_ref="ORD-002",
    )
    assert success is False
    assert status == VoucherStatus.LIMIT_EXCEEDED
    assert "breach" in reason.lower()

    # 4. Successful redemption within domain and monetary limits
    voucher3 = facade.issue_merchant_voucher(
        identity_id="eph-id-test-1",
        target_merchant_domain="api.aws.amazon.com",
        max_authorized_amount=150.0,
        currency="USD",
    )
    success, status, reason, updated_v = facade.redeem_merchant_voucher(
        voucher_id=voucher3.voucher_id,
        single_use_token=voucher3.single_use_token,
        request_domain="api.aws.amazon.com",
        requested_amount=99.99,
        order_ref="AWS-INV-7721",
    )
    assert success is True
    assert status == VoucherStatus.REDEEMED
    assert updated_v is not None
    assert updated_v.redeemed_amount == 99.99
    assert updated_v.merchant_order_ref == "AWS-INV-7721"

    # 5. Replay attempt should be blocked
    success, status, reason, _ = facade.redeem_merchant_voucher(
        voucher_id=voucher3.voucher_id,
        single_use_token=voucher3.single_use_token,
        request_domain="api.aws.amazon.com",
        requested_amount=10.0,
    )
    assert success is False
    assert "cannot be redeemed" in reason


def test_merkle_tree_audit_trail_and_proof_bundle() -> None:
    """Test four-phase audit logging, Merkle root computation, tamper-proofing, and bundle export."""
    facade = EphemeralIdentityAndVoucherFacade()
    task_id = "task-flight-purchase-4091"

    # Phase 1: User Intent
    ev1: AuditEventRecord = facade.record_audit_phase(
        task_id=task_id,
        phase=AuditPhase.PHASE_1_USER_INTENT,
        summary="User approved ticket purchase for SFO -> JFK flight",
        structured_payload={"user_id": "usr_99", "max_price": "450.00", "currency": "USD"},
    )
    assert ev1.phase == AuditPhase.PHASE_1_USER_INTENT
    assert ev1.parent_hash is None

    # Phase 2: Credential Grant
    ev2: AuditEventRecord = facade.record_audit_phase(
        task_id=task_id,
        phase=AuditPhase.PHASE_2_CREDENTIAL_GRANT,
        summary="Granted ephemeral token and domain-locked voucher for airline.com",
        structured_payload={"merchant": "airline.com", "voucher_cap": "450.00"},
    )
    assert ev2.parent_hash == ev1.node_hash

    # Phase 3: Execution Snapshot
    ev3: AuditEventRecord = facade.record_audit_phase(
        task_id=task_id,
        phase=AuditPhase.PHASE_3_EXECUTION_SNAPSHOT,
        summary="Browser sandbox completed checkout form fill and submit click",
        structured_payload={"dom_state_hash": "a1b2c3d4", "url": "https://airline.com/checkout"},
    )
    assert ev3.parent_hash == ev2.node_hash

    # Phase 4: Settlement Receipt
    ev4: AuditEventRecord = facade.record_audit_phase(
        task_id=task_id,
        phase=AuditPhase.PHASE_4_SETTLEMENT_RECEIPT,
        summary="Payment cleared with confirmation PNR #K9X72P",
        structured_payload={"pnr": "K9X72P", "charged": "428.50", "status": "CONFIRMED"},
    )
    assert ev4.parent_hash == ev3.node_hash

    # Verify integrity
    is_valid, _reason, merkle_root = facade.verify_audit_trail(task_id)
    assert is_valid is True
    assert merkle_root is not None
    assert len(merkle_root) == 64

    # Export bundle
    bundle: AuditProofBundle = facade.export_proof_bundle(task_id)
    assert bundle.task_id == task_id
    assert bundle.merkle_root == merkle_root
    assert len(bundle.events) == 4
    assert len(bundle.phases_included) == 4
    assert bundle.verification_success is True

    # Metrics check
    metrics = facade.metrics
    assert metrics.audit_events_recorded_total == 4
