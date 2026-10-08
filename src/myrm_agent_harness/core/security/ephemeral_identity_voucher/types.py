"""
[POS] src/myrm_agent_harness/core/security/ephemeral_identity_voucher/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] IdentityStatus, VoucherStatus, AuditPhase, EphemeralIdentity, MerchantLockedVoucher, AuditEventRecord, AuditProofBundle, EphemeralIdentityMetrics

Domain types for Dynamic Ephemeral Identity & Verifiable Audit Trail Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class IdentityStatus(StrEnum):
    """Lifecycle status for an ephemeral identity credential."""

    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class VoucherStatus(StrEnum):
    """Lifecycle status for a merchant-locked disposable payment voucher."""

    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    DOMAIN_MISMATCH = "DOMAIN_MISMATCH"


class AuditPhase(StrEnum):
    """The four closed-loop phases for irreversible or privileged autonomous operations."""

    PHASE_1_USER_INTENT = "USER_INTENT"
    PHASE_2_CREDENTIAL_GRANT = "CREDENTIAL_GRANT"
    PHASE_3_EXECUTION_SNAPSHOT = "EXECUTION_SNAPSHOT"
    PHASE_4_SETTLEMENT_RECEIPT = "SETTLEMENT_RECEIPT"


@dataclass(frozen=True)
class EphemeralIdentity:
    """Dynamically provisioned short-lived identity credential, self-destructing on timeout."""

    identity_id: str
    agent_id: str
    task_id: str
    allowed_scopes: tuple[str, ...]
    ephemeral_token: str
    created_at_epoch: float
    expires_at_epoch: float
    status: IdentityStatus
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MerchantLockedVoucher:
    """Disposable payment voucher strictly locked to a specific domain and monetary cap."""

    voucher_id: str
    identity_id: str
    target_merchant_domain: str
    max_authorized_amount: float
    currency: str
    single_use_token: str
    created_at_epoch: float
    expires_at_epoch: float
    status: VoucherStatus
    redeemed_amount: float = 0.0
    merchant_order_ref: str | None = None


@dataclass(frozen=True)
class AuditEventRecord:
    """Cryptographically chained atomic audit record within an autonomous task execution."""

    event_id: str
    task_id: str
    phase: AuditPhase
    timestamp_epoch: float
    payload_hash: str
    raw_summary: str
    parent_hash: str | None
    node_hash: str


@dataclass(frozen=True)
class AuditProofBundle:
    """Tamper-proof verifiable Merkle tree export package with non-repudiation evidence."""

    task_id: str
    merkle_root: str
    phases_included: tuple[str, ...]
    events: tuple[AuditEventRecord, ...]
    verification_success: bool
    exported_at_epoch: float


@dataclass
class EphemeralIdentityMetrics:
    """Operational metrics for ephemeral credentials, merchant vouchers, and audit ledger."""

    identities_issued_total: int = 0
    identities_revoked_total: int = 0
    identities_expired_total: int = 0
    vouchers_issued_total: int = 0
    vouchers_redeemed_total: int = 0
    vouchers_rejected_total: int = 0
    audit_events_recorded_total: int = 0
