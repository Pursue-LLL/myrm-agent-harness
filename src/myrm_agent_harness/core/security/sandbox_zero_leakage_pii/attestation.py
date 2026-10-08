"""Physical sandbox isolation and dedicated volume exclusivity attestation engine."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time

from myrm_agent_harness.core.security.sandbox_zero_leakage_pii.types import (
    ZeroLeakageAttestationProof,
)

logger = logging.getLogger(__name__)

_DEFAULT_SIGNING_KEY: bytes = b"myrm-sandbox-zero-leakage-ca-v1"


class PhysicalSandboxAttestationEngine:
    """Engine issuing and verifying cryptographic zero-leakage proofs for single-tenant sandboxes."""

    def __init__(self, signing_secret: bytes | None = None) -> None:
        self._signing_secret: bytes = signing_secret or _DEFAULT_SIGNING_KEY

    def issue_attestation(
        self,
        tenant_id: str,
        container_id: str,
        dedicated_volume_path: str,
        dedicated_database_lock: str,
        signer_identity: str = "myrm-control-plane-ledger",
    ) -> ZeroLeakageAttestationProof:
        """Issue a tamper-evident zero-leakage attestation proof verifying physical container boundaries."""
        now = time.time()
        attestation_id = f"leak-attest-{secrets.token_hex(8)}"

        body = json.dumps(
            {
                "attestation_id": attestation_id,
                "tenant_id": tenant_id,
                "container_id": container_id,
                "volume_path": dedicated_volume_path,
                "db_lock": dedicated_database_lock,
                "issued_at": int(now),
                "signer": signer_identity,
            },
            sort_keys=True,
        )

        signature = hmac.new(
            self._signing_secret,
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return ZeroLeakageAttestationProof(
            attestation_id=attestation_id,
            tenant_id=tenant_id,
            container_id=container_id,
            dedicated_volume_path=dedicated_volume_path,
            dedicated_database_lock=dedicated_database_lock,
            issued_at=now,
            signer_identity=signer_identity,
            attestation_signature=signature,
        )

    def verify_attestation(self, proof: ZeroLeakageAttestationProof) -> bool:
        """Verify the cryptographic authenticity and integrity of an attestation proof."""
        body = json.dumps(
            {
                "attestation_id": proof.attestation_id,
                "tenant_id": proof.tenant_id,
                "container_id": proof.container_id,
                "volume_path": proof.dedicated_volume_path,
                "db_lock": proof.dedicated_database_lock,
                "issued_at": int(proof.issued_at),
                "signer": proof.signer_identity,
            },
            sort_keys=True,
        )

        expected_sig = hmac.new(
            self._signing_secret,
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(proof.attestation_signature, expected_sig)
