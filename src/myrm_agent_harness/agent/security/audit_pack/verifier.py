"""Offline verifier for validating authenticity and non-repudiation of legal audit dockets.

[POS]
Provides standalone offline verification of root digest integrity and HMAC-SHA256 signature seals.
Can be executed by external auditors, compliance officers, and legal teams without server dependency.
"""

from __future__ import annotations

import hashlib
import hmac

from myrm_agent_harness.agent.security.audit_pack.models import LegalAuditDocket


class LegalAuditDocketVerifier:
    """Verifier for evaluating authenticity of sealed LegalAuditDocket dossiers."""

    @classmethod
    def verify_docket(
        cls,
        docket: LegalAuditDocket,
        signing_secret: str,
    ) -> tuple[bool, str | None]:
        """Verify root digest matches canonical content and signature seal is valid.

        Returns:
            (is_valid, failure_reason)
        """
        # Step 1: Recompute canonical root digest
        canonical_json = docket.to_canonical_json()
        expected_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        if expected_digest != docket.root_digest:
            return (
                False,
                f"Root digest mismatch: docket content was tampered. Expected {expected_digest[:16]}, "
                f"recorded {docket.root_digest[:16]}",
            )

        # Step 2: Verify cryptographic signature seal
        if docket.signature is None:
            return False, "Docket lacks a cryptographic signature seal"

        expected_sig = hmac.new(
            signing_secret.encode("utf-8"),
            docket.root_digest.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, docket.signature.signature_value):
            return (
                False,
                "Cryptographic signature seal verification failed: forged signature or wrong signing key",
            )

        return True, None
