"""
[POS] src/myrm_agent_harness/core/security/ephemeral_identity_voucher/facade.py
[INPUT] types, ephemeral_identity_broker, merchant_locked_voucher_manager, merkle_audit_ledger
[OUTPUT] EphemeralIdentityAndVoucherFacade

Unified facade aggregating ephemeral identities, merchant vouchers, and Merkle audit ledgers.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .ephemeral_identity_broker import DynamicEphemeralIdentityBroker
from .merchant_locked_voucher_manager import MerchantLockedVoucherManager
from .merkle_audit_ledger import MerkleTreeAuditLedger
from .types import (
    AuditEventRecord,
    AuditPhase,
    AuditProofBundle,
    EphemeralIdentity,
    EphemeralIdentityMetrics,
    IdentityStatus,
    MerchantLockedVoucher,
    VoucherStatus,
)


class EphemeralIdentityAndVoucherFacade:
    """Unified entrypoint for the Ephemeral Identity, Merchant Voucher & Merkle Audit Suite."""

    def __init__(self) -> None:
        self._metrics = EphemeralIdentityMetrics()
        self._broker = DynamicEphemeralIdentityBroker(metrics=self._metrics)
        self._voucher_manager = MerchantLockedVoucherManager(metrics=self._metrics)
        self._audit_ledger = MerkleTreeAuditLedger(metrics=self._metrics)

    @property
    def metrics(self) -> EphemeralIdentityMetrics:
        """Shared operational metrics."""
        return self._metrics

    def issue_ephemeral_identity(
        self,
        agent_id: str,
        task_id: str,
        allowed_scopes: tuple[str, ...],
        ttl_seconds: float = DynamicEphemeralIdentityBroker.DEFAULT_TTL_SECONDS,
        metadata: dict[str, str] | None = None,
    ) -> EphemeralIdentity:
        """Dynamically provision a short-lived micro-scoped identity."""
        return self._broker.issue_identity(
            agent_id=agent_id,
            task_id=task_id,
            allowed_scopes=allowed_scopes,
            ttl_seconds=ttl_seconds,
            metadata=metadata,
        )

    def verify_ephemeral_identity(
        self,
        identity_id: str,
        token: str,
        required_scope: str | None = None,
    ) -> tuple[bool, IdentityStatus, str]:
        """Verify token authenticity, scope validity, and expiration."""
        return self._broker.verify_identity(
            identity_id=identity_id,
            token=token,
            required_scope=required_scope,
        )

    def revoke_ephemeral_identity(
        self, identity_id: str, reason: str = "Admin revocation"
    ) -> bool:
        """Immediately revoke an ephemeral identity."""
        return self._broker.revoke_identity(identity_id=identity_id, reason=reason)

    def consume_ephemeral_identity(self, identity_id: str) -> bool:
        """Single-use destruction of an active ephemeral identity."""
        return self._broker.consume_identity(identity_id=identity_id)

    def consume_identity(self, identity_id: str) -> bool:
        """Single-use destruction of an active ephemeral identity (alias)."""
        return self._broker.consume_identity(identity_id=identity_id)

    def get_identity(self, identity_id: str) -> EphemeralIdentity | None:
        """Retrieve identity record if exists."""
        return self._broker.get_identity(identity_id=identity_id)

    def issue_merchant_voucher(
        self,
        identity_id: str,
        target_merchant_domain: str,
        max_authorized_amount: float,
        currency: str = "USD",
        ttl_seconds: float = MerchantLockedVoucherManager.DEFAULT_VOUCHER_TTL_SECONDS,
    ) -> MerchantLockedVoucher:
        """Issue a domain-locked, single-use, capped virtual payment voucher."""
        return self._voucher_manager.issue_voucher(
            identity_id=identity_id,
            target_merchant_domain=target_merchant_domain,
            max_authorized_amount=max_authorized_amount,
            currency=currency,
            ttl_seconds=ttl_seconds,
        )

    def redeem_merchant_voucher(
        self,
        voucher_id: str,
        single_use_token: str,
        request_domain: str,
        requested_amount: float,
        order_ref: str | None = None,
    ) -> tuple[bool, VoucherStatus, str, MerchantLockedVoucher | None]:
        """Validate and redeem a domain-locked voucher."""
        return self._voucher_manager.redeem_voucher(
            voucher_id=voucher_id,
            single_use_token=single_use_token,
            request_domain=request_domain,
            requested_amount=requested_amount,
            order_ref=order_ref,
        )

    def void_merchant_voucher(
        self, voucher_id: str, reason: str = "Admin void"
    ) -> bool:
        """Void an unspent payment voucher."""
        return self._voucher_manager.void_voucher(voucher_id=voucher_id, reason=reason)

    def get_voucher(self, voucher_id: str) -> MerchantLockedVoucher | None:
        """Lookup voucher details."""
        return self._voucher_manager.get_voucher(voucher_id=voucher_id)

    def record_audit_phase(
        self,
        task_id: str,
        phase: AuditPhase,
        summary: str,
        structured_payload: dict[str, str],
        timestamp_epoch: float | None = None,
    ) -> AuditEventRecord:
        """Append an immutable cryptographically chained audit event."""
        return self._audit_ledger.record_phase_event(
            task_id=task_id,
            phase=phase,
            summary=summary,
            structured_payload=structured_payload,
            timestamp_epoch=timestamp_epoch,
        )

    def verify_audit_trail(self, task_id: str) -> tuple[bool, str, str | None]:
        """Verify chain integrity and compute current Merkle root."""
        return self._audit_ledger.verify_integrity(task_id=task_id)

    def export_proof_bundle(self, task_id: str) -> AuditProofBundle:
        """Export verifiable cryptographic proof bundle for compliance audits."""
        return self._audit_ledger.export_proof_bundle(task_id=task_id)
