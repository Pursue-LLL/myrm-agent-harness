"""Types and models for pairing.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- PasskeyAlgorithmKind: Supported cryptographic signature algorithms for Passkey credentials.
- DeviceTrustState: Lifecycle trust status for registered client devices.
- PairingTicket: One-time dynamic pairing ticket rendered into QR code.
- PasskeyCredential: Registered hardware or secure-enclave client passkey credential.
- AuthChallenge: One-time server-issued challenge nonce for zero-password login.
- ChallengeResponse: Client hardware signature payload submitted in response to challenge.
- DiscoveredServiceBeacon: Local network mDNS/Bonjour service beacon advertisement.

[POS]
Types and models for pairing.
"""

# ============================================================================
# Cross-Device Fast Pairing & Passkey Data Contracts (Item 160)
# Strong typing contracts for QR bootstrap, Passkey/WebAuthn hardware credentials,
# challenge-response authentication, and device vault revocation governance.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class PasskeyAlgorithmKind(str, Enum):
    """Supported cryptographic signature algorithms for Passkey credentials."""

    ED25519 = "Ed25519"
    ES256 = "ES256"
    HMAC_SHA256 = "HMAC-SHA256"


class DeviceTrustState(str, Enum):
    """Lifecycle trust status for registered client devices."""

    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class PairingTicket:
    """One-time dynamic pairing ticket rendered into QR code."""

    ticket_id: str
    challenge: str
    qr_payload: str
    expires_at_iso: str
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    is_consumed: bool = False


@dataclass(frozen=True, slots=True)
class PasskeyCredential:
    """Registered hardware or secure-enclave client passkey credential."""

    credential_id: str
    device_id: str
    device_name: str
    public_key_pem: str
    algorithm: PasskeyAlgorithmKind
    created_at_iso: str
    last_used_iso: str
    trust_state: DeviceTrustState


@dataclass(frozen=True, slots=True)
class AuthChallenge:
    """One-time server-issued challenge nonce for zero-password login."""

    challenge_id: str
    credential_id: str
    nonce: str
    expires_at_iso: str


@dataclass(frozen=True, slots=True)
class ChallengeResponse:
    """Client hardware signature payload submitted in response to challenge."""

    challenge_id: str
    credential_id: str
    signature_hex: str


@dataclass(frozen=True, slots=True)
class DiscoveredServiceBeacon:
    """Local network mDNS/Bonjour service beacon advertisement."""

    service_name: str
    host: str
    port: int
    instance_fingerprint: str
    is_local: bool = True
