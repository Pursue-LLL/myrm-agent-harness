"""Generates dynamic pairing tickets and formatted QR code bootstrap payloads.

[INPUT]
- agent.context_management.pairing.pairing_types::AuthChallenge, ChallengeResponse, DeviceTrustState,
  DiscoveredServiceBeacon, PairingTicket, PasskeyAlgorithmKind, PasskeyCredential (POS: Types and models for
  pairing.)

[OUTPUT]
- PairingQrBootstrapEngine: Generates dynamic pairing tickets and formatted QR code bootstrap payloads.
- DeviceAuthVault: Manages registered Passkey hardware credentials and revocation governance.
- PasskeyChallengeAuthenticator: Authenticates client hardware devices via cryptographic challenge-response.
- LocalDiscoveryBeaconManager: Generates and validates local area network Bonjour/mDNS service beacon
  advertisements.

[POS]
Generates dynamic pairing tickets and formatted QR code bootstrap payloads.
"""

# ============================================================================
# Cross-Device Fast Pairing Gateway & Passkey Authenticator (Item 160)
# Manages dynamic QR code bootstrap pairing, Passkey hardware credentials,
# challenge-response cryptographic verification, and device revocation cockpit.
# ============================================================================

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Sequence

from .pairing_types import (
    AuthChallenge,
    ChallengeResponse,
    DeviceTrustState,
    DiscoveredServiceBeacon,
    PairingTicket,
    PasskeyAlgorithmKind,
    PasskeyCredential,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str)


class PairingQrBootstrapEngine:
    """Generates dynamic pairing tickets and formatted QR code bootstrap payloads."""

    def __init__(self, default_ttl_seconds: int = 300) -> None:
        self._default_ttl_seconds = default_ttl_seconds
        self._tickets: dict[str, PairingTicket] = {}

    def create_pairing_ticket(self, ttl_seconds: int | None = None) -> PairingTicket:
        """Create a fresh ephemeral pairing ticket with high-entropy challenge."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        ticket_id = f"ticket-{uuid.uuid4().hex[:12]}"
        challenge = secrets.token_hex(32)
        exp_iso = (_utc_now() + timedelta(seconds=ttl)).isoformat()

        qr_payload = (
            f"myrm://pair?ticket={ticket_id}&challenge={challenge}&exp={exp_iso}"
        )

        ticket = PairingTicket(
            ticket_id=ticket_id,
            challenge=challenge,
            qr_payload=qr_payload,
            expires_at_iso=exp_iso,
            is_consumed=False,
        )
        self._tickets[ticket_id] = ticket
        return ticket

    def consume_pairing_ticket(self, ticket_id: str, challenge: str) -> bool:
        """Verify and consume a pairing ticket in a single atomic turn."""
        ticket = self._tickets.get(ticket_id)
        if ticket is None or ticket.is_consumed:
            return False

        # Verify expiration
        exp_dt = _parse_iso(ticket.expires_at_iso)
        if _utc_now() > exp_dt:
            return False

        # Constant-time challenge comparison to avoid timing attacks
        if not hmac.compare_digest(ticket.challenge, challenge):
            return False

        # Mark consumed
        consumed_ticket = PairingTicket(
            ticket_id=ticket.ticket_id,
            challenge=ticket.challenge,
            qr_payload=ticket.qr_payload,
            expires_at_iso=ticket.expires_at_iso,
            created_at_iso=ticket.created_at_iso,
            is_consumed=True,
        )
        self._tickets[ticket_id] = consumed_ticket
        return True

    @staticmethod
    def render_ascii_qr_preview(ticket: PairingTicket) -> str:
        """Render high-contrast ASCII terminal block for CLI QR code display."""
        border = "+--------------------------------------------------------+"
        title = f"| SCAN QR TO PAIR: {ticket.ticket_id:<36} |"
        payload_line = f"| URI: {ticket.qr_payload[:50]}... |"
        matrix = [
            "|  ##  ####  ##    ##    ####  ##  |",
            "|  ##  #  #  ##    ##    #  #  ##  |",
            "|  ##  ####  ##    ##    ####  ##  |",
            "|  ####      ########    ####      |",
            "|  ##  ####  ##    ##    ####  ##  |",
        ]
        lines = [border, title, border] + matrix + [border, payload_line, border]
        return "\n".join(lines)


class DeviceAuthVault:
    """Manages registered Passkey hardware credentials and revocation governance."""

    def __init__(self) -> None:
        self._credentials: dict[str, PasskeyCredential] = {}

    def register_credential(self, credential: PasskeyCredential) -> PasskeyCredential:
        """Register a new verified device Passkey credential into the vault."""
        self._credentials[credential.credential_id] = credential
        logger.info(
            "Registered Passkey device '%s' (credential_id: %s)",
            credential.device_name,
            credential.credential_id,
        )
        return credential

    def get_credential(self, credential_id: str) -> PasskeyCredential | None:
        """Get credential by ID or None if absent."""
        return self._credentials.get(credential_id)

    def revoke_credential(self, credential_id: str) -> bool:
        """Revoke device authorization immediately."""
        cred = self._credentials.get(credential_id)
        if cred is None:
            return False

        revoked = PasskeyCredential(
            credential_id=cred.credential_id,
            device_id=cred.device_id,
            device_name=cred.device_name,
            public_key_pem=cred.public_key_pem,
            algorithm=cred.algorithm,
            created_at_iso=cred.created_at_iso,
            last_used_iso=cred.last_used_iso,
            trust_state=DeviceTrustState.REVOKED,
        )
        self._credentials[credential_id] = revoked
        logger.warning(
            "Device Passkey credential '%s' revoked from vault.", credential_id
        )
        return True

    def mark_last_used(self, credential_id: str) -> None:
        """Update last active timestamp of verified credential."""
        cred = self._credentials.get(credential_id)
        if cred is None:
            return

        updated = PasskeyCredential(
            credential_id=cred.credential_id,
            device_id=cred.device_id,
            device_name=cred.device_name,
            public_key_pem=cred.public_key_pem,
            algorithm=cred.algorithm,
            created_at_iso=cred.created_at_iso,
            last_used_iso=_utc_now().isoformat(),
            trust_state=cred.trust_state,
        )
        self._credentials[credential_id] = updated

    def list_credentials(self) -> tuple[PasskeyCredential, ...]:
        """List all credentials in vault."""
        return tuple(self._credentials.values())


class PasskeyChallengeAuthenticator:
    """Authenticates client hardware devices via cryptographic challenge-response."""

    def __init__(
        self,
        vault: DeviceAuthVault,
        default_challenge_ttl_seconds: int = 120,
    ) -> None:
        self._vault = vault
        self._ttl_seconds = default_challenge_ttl_seconds
        self._active_challenges: dict[str, AuthChallenge] = {}

    def create_challenge(self, credential_id: str) -> AuthChallenge:
        """Issue a fresh single-use cryptographic challenge for client signature."""
        cred = self._vault.get_credential(credential_id)
        if cred is None:
            raise KeyError(f"Credential '{credential_id}' not found in vault.")
        if cred.trust_state != DeviceTrustState.ACTIVE:
            raise PermissionError(
                f"Credential '{credential_id}' is not in active state ({cred.trust_state.value})."
            )

        challenge_id = f"chal-{uuid.uuid4().hex[:12]}"
        nonce = secrets.token_hex(32)
        exp_iso = (_utc_now() + timedelta(seconds=self._ttl_seconds)).isoformat()

        challenge = AuthChallenge(
            challenge_id=challenge_id,
            credential_id=credential_id,
            nonce=nonce,
            expires_at_iso=exp_iso,
        )
        self._active_challenges[challenge_id] = challenge
        return challenge

    def verify_response(
        self,
        response: ChallengeResponse,
        signature_verifier: Callable[[str, str, str], bool] | None = None,
    ) -> bool:
        """Verify client response signature against challenge and registered key.

        Args:
            response: Challenge response with challenge_id, credential_id, and signature_hex.
            signature_verifier: Optional custom verifier(nonce, signature_hex, public_key_pem).
                If None, uses standard SHA-256 HMAC digest verification with public_key_pem as key.
        """
        challenge = self._active_challenges.get(response.challenge_id)
        if challenge is None or challenge.credential_id != response.credential_id:
            return False

        # Consume challenge so it cannot be replayed
        self._active_challenges.pop(response.challenge_id, None)

        if _utc_now() > _parse_iso(challenge.expires_at_iso):
            return False

        cred = self._vault.get_credential(response.credential_id)
        if cred is None or cred.trust_state != DeviceTrustState.ACTIVE:
            return False

        # Verify signature
        if signature_verifier is not None:
            is_valid = signature_verifier(
                challenge.nonce,
                response.signature_hex,
                cred.public_key_pem,
            )
        else:
            # Default HMAC verification
            expected = hmac.new(
                cred.public_key_pem.encode("utf-8"),
                challenge.nonce.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            is_valid = hmac.compare_digest(expected, response.signature_hex)

        if is_valid:
            self._vault.mark_last_used(cred.credential_id)
            return True
        return False


class LocalDiscoveryBeaconManager:
    """Generates and validates local area network Bonjour/mDNS service beacon advertisements."""

    @staticmethod
    def create_beacon(
        service_name: str,
        host: str,
        port: int,
        instance_fingerprint: str,
    ) -> DiscoveredServiceBeacon:
        """Generate advertisement beacon for local network mobile autodiscovery."""
        return DiscoveredServiceBeacon(
            service_name=service_name,
            host=host,
            port=port,
            instance_fingerprint=instance_fingerprint,
            is_local=True,
        )

    @staticmethod
    def validate_beacon(beacon: DiscoveredServiceBeacon) -> bool:
        """Validate local beacon configuration validity."""
        if not beacon.service_name or not beacon.host or beacon.port <= 0 or beacon.port > 65535:
            return False
        if not beacon.instance_fingerprint:
            return False
        return True
