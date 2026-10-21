"""Core data structures and types for Inbound Zero-Trust Quarantine & Redaction.

[INPUT]
- Raw email, chat, or webhook inbound messages and metadata.

[OUTPUT]
- Strongly-typed risk classifications, physical quarantine records, and release card models.

[POS]
- Harness core security contracts for inbound credential isolation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class InboundQuarantineRiskType(StrEnum):
    """Categories of sensitive inbound credentials requiring physical quarantine."""

    OTP_2FA = "OTP_2FA"
    PASSWORD_RESET = "PASSWORD_RESET"
    FINANCIAL_STATEMENT = "FINANCIAL_STATEMENT"
    API_TOKEN = "API_TOKEN"


class InboundQuarantineStatus(StrEnum):
    """Lifecycle status of a physically quarantined inbound message."""

    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    PURGED = "PURGED"


@dataclass(frozen=True)
class QuarantineDetectionResult:
    """Detection outcome and filtered content safe for model ingestion."""

    is_quarantined: bool
    detected_risks: list[InboundQuarantineRiskType] = field(default_factory=list)
    safe_content: str = ""
    quarantine_id: str | None = None
    release_card_url: str | None = None
    expires_at: float | None = None


@dataclass
class QuarantineRecord:
    """Encrypted physical vault record for quarantined message content."""

    quarantine_id: str
    channel_type: str
    sender: str
    recipient: str
    ciphertext_b64: str
    nonce_b64: str
    detected_risks: list[InboundQuarantineRiskType]
    status: InboundQuarantineStatus = InboundQuarantineStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0


@dataclass(frozen=True)
class ReleasedSecretInfo:
    """Decrypted payload accessible strictly by authenticated human users."""

    quarantine_id: str
    detected_risks: list[InboundQuarantineRiskType]
    original_content: str
    released_at: float
