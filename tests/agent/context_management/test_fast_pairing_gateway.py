# ============================================================================
# Unit Tests for Cross-Device Fast Pairing & Passkey Authenticator (Item 160)
# ============================================================================

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

import pytest

from myrm_agent_harness.agent.context_management.pairing import (
    AuthChallenge,
    ChallengeResponse,
    DeviceAuthVault,
    DeviceTrustState,
    DiscoveredServiceBeacon,
    LocalDiscoveryBeaconManager,
    PairingQrBootstrapEngine,
    PairingTicket,
    PasskeyAlgorithmKind,
    PasskeyChallengeAuthenticator,
    PasskeyCredential,
)


def test_pairing_qr_bootstrap_creation_consumption_and_ascii() -> None:
    """Validate ephemeral QR pairing ticket creation, consumption, and replay defense."""
    engine = PairingQrBootstrapEngine(default_ttl_seconds=120)

    # 1. Create ticket
    ticket = engine.create_pairing_ticket()
    assert ticket.ticket_id.startswith("ticket-")
    assert len(ticket.challenge) == 64
    assert "myrm://pair?ticket=" in ticket.qr_payload
    assert ticket.is_consumed is False

    # 2. Render ASCII preview
    ascii_qr = engine.render_ascii_qr_preview(ticket)
    assert ticket.ticket_id in ascii_qr
    assert "SCAN QR TO PAIR" in ascii_qr

    # 3. Wrong challenge fails
    assert engine.consume_pairing_ticket(ticket.ticket_id, "wrong_challenge_hex") is False

    # 4. Valid challenge consumes ticket
    assert engine.consume_pairing_ticket(ticket.ticket_id, ticket.challenge) is True

    # 5. Replay fails (already consumed)
    assert engine.consume_pairing_ticket(ticket.ticket_id, ticket.challenge) is False


def test_device_auth_vault_registration_and_revocation() -> None:
    """Validate Passkey device registration, lookup, and revocation."""
    vault = DeviceAuthVault()
    now_iso = datetime.now(timezone.utc).isoformat()

    cred = PasskeyCredential(
        credential_id="cred-apple-enclave-01",
        device_id="iphone-15-pro-max",
        device_name="Alice's iPhone",
        public_key_pem="secret_shared_key_or_pubkey_bytes",
        algorithm=PasskeyAlgorithmKind.HMAC_SHA256,
        created_at_iso=now_iso,
        last_used_iso=now_iso,
        trust_state=DeviceTrustState.ACTIVE,
    )

    vault.register_credential(cred)
    retrieved = vault.get_credential("cred-apple-enclave-01")
    assert retrieved is not None
    assert retrieved.device_name == "Alice's iPhone"
    assert retrieved.trust_state == DeviceTrustState.ACTIVE

    # List active credentials
    all_creds = vault.list_credentials()
    assert len(all_creds) == 1

    # Revoke device
    assert vault.revoke_credential("cred-apple-enclave-01") is True
    revoked = vault.get_credential("cred-apple-enclave-01")
    assert revoked is not None
    assert revoked.trust_state == DeviceTrustState.REVOKED


def test_passkey_challenge_response_authentication() -> None:
    """Validate cryptographic challenge issuance and signature verification flow."""
    vault = DeviceAuthVault()
    secret_key = "device_hardware_passkey_key_32bytes"
    now_iso = datetime.now(timezone.utc).isoformat()

    cred = PasskeyCredential(
        credential_id="cred-passkey-101",
        device_id="macbook-air-m2",
        device_name="Bob's MacBook",
        public_key_pem=secret_key,
        algorithm=PasskeyAlgorithmKind.HMAC_SHA256,
        created_at_iso=now_iso,
        last_used_iso=now_iso,
        trust_state=DeviceTrustState.ACTIVE,
    )
    vault.register_credential(cred)

    auth = PasskeyChallengeAuthenticator(vault=vault, default_challenge_ttl_seconds=60)

    # 1. Issue challenge
    challenge = auth.create_challenge("cred-passkey-101")
    assert challenge.credential_id == "cred-passkey-101"
    assert len(challenge.nonce) == 64

    # 2. Client signs nonce with local key
    valid_sig = hmac.new(
        secret_key.encode("utf-8"),
        challenge.nonce.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # 3. Invalid signature fails
    invalid_resp = ChallengeResponse(
        challenge_id=challenge.challenge_id,
        credential_id="cred-passkey-101",
        signature_hex="deadbeefcafebabe0000",
    )
    # Invalid response consumes the challenge to avoid brute force
    assert auth.verify_response(invalid_resp) is False

    # 4. Issue a new challenge and verify with valid signature
    chal2 = auth.create_challenge("cred-passkey-101")
    valid_sig2 = hmac.new(
        secret_key.encode("utf-8"),
        chal2.nonce.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    valid_resp = ChallengeResponse(
        challenge_id=chal2.challenge_id,
        credential_id="cred-passkey-101",
        signature_hex=valid_sig2,
    )
    assert auth.verify_response(valid_resp) is True

    # 5. Revoked device cannot issue challenge
    vault.revoke_credential("cred-passkey-101")
    with pytest.raises(PermissionError):
        auth.create_challenge("cred-passkey-101")


def test_local_discovery_beacon_manager() -> None:
    """Validate mDNS beacon creation and parameter validation."""
    beacon = LocalDiscoveryBeaconManager.create_beacon(
        service_name="Myrm-Mac-Mini._myrm._tcp.local.",
        host="192.168.1.88",
        port=8000,
        instance_fingerprint="sha256:d8f45a192bc",
    )

    assert LocalDiscoveryBeaconManager.validate_beacon(beacon) is True
    assert beacon.is_local is True

    # Invalid port
    bad_beacon = DiscoveredServiceBeacon(
        service_name="Myrm-Bad",
        host="192.168.1.88",
        port=70000,  # invalid port > 65535
        instance_fingerprint="sha256:abc",
    )
    assert LocalDiscoveryBeaconManager.validate_beacon(bad_beacon) is False
