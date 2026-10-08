"""
[POS] src/myrm_agent_harness/core/security/confidential_payment_sandbox/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] EnclaveAttestationStatus, VirtualCardStatus, IngressFenceMode, ConfidentialEnclaveAttestation, SingleUseVirtualCard, VirtualCardPaymentRequest, VirtualCardPaymentReceipt, DualSentinelScanResult, ConfidentialPaymentMetrics
Domain types for Confidential VM Hardware Isolation & Single-Use Virtual Card Payment Proxy Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EnclaveAttestationStatus(StrEnum):
    """Status of remote hardware cryptographic attestation."""

    UNVERIFIED = "unverified"
    VERIFIED_HARDWARE_SEV_SNP = "verified_hardware_sev_snp"
    VERIFIED_HARDWARE_TDX = "verified_hardware_tdx"
    VERIFIED_SOFTWARE_EMULATED = "verified_software_emulated"
    FAILED = "failed"


class VirtualCardStatus(StrEnum):
    """Lifecycle states of a single-use virtual payment card."""

    ACTIVE = "active"
    REDEEMED = "redeemed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class IngressFenceMode(StrEnum):
    """External service channel access restrictions."""

    READ_ONLY = "read_only"
    ELEVATED_WRITE_PERMITTED = "elevated_write_permitted"


@dataclass(frozen=True)
class ConfidentialEnclaveAttestation:
    """Hardware enclave remote attestation proof verifying memory encryption."""

    enclave_id: str
    platform_type: str
    status: EnclaveAttestationStatus
    measurement_sha256: str
    attested_at: float
    is_memory_encrypted: bool
    diagnostic: str


@dataclass(frozen=True)
class SingleUseVirtualCard:
    """Disposable virtual card token isolated from plain card credentials."""

    card_token: str
    masked_card_number: str
    currency: str
    spending_limit: float
    amount_spent: float
    status: VirtualCardStatus
    created_at: float
    expires_at: float
    requires_hitl: bool


@dataclass(frozen=True)
class VirtualCardPaymentRequest:
    """Payment transaction request submitted by autonomous agent."""

    card_token: str
    amount: float
    currency: str
    merchant_name: str
    item_description: str
    idempotency_key: str


@dataclass(frozen=True)
class VirtualCardPaymentReceipt:
    """Settlement outcome for a single-use virtual card charge."""

    receipt_id: str
    card_token: str
    charged_amount: float
    currency: str
    is_success: bool
    status: str
    merchant_name: str
    requires_hitl_escalation: bool
    message: str


@dataclass(frozen=True)
class DualSentinelScanResult:
    """Inspection outcome of ingress/egress bidirectional sentinel."""

    direction: str  # "ingress" or "egress"
    is_blocked: bool
    detected_threats: tuple[str, ...]
    sanitized_content: str
    diagnostic: str


@dataclass
class ConfidentialPaymentMetrics:
    """Operational telemetry counters for confidential enclaves and virtual card transactions."""

    attestations_verified_total: int = 0
    cards_issued_total: int = 0
    payments_processed_total: int = 0
    hitl_escalations_total: int = 0
    ingress_injections_blocked_total: int = 0
    egress_leaks_prevented_total: int = 0
