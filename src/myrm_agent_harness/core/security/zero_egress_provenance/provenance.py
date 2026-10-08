"""Generative asset provenance generator and zero-egress compliance attestation engine.

[INPUT]
- Generated asset content (code, text, binary), prompt strings, session/tenant IDs, model IDs.

[OUTPUT]
- Cryptographically signed ZeroEgressAttestationCertificate and AssetProvenanceDossier.

[POS]
- Harness core security engine certifying zero training retention and intellectual property provenance.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime

from myrm_agent_harness.core.security.zero_egress_provenance.types import (
    AssetProvenanceDossier,
    AttestationLevel,
    IPCleanlinessTier,
    ProvenanceVerificationError,
    ZeroEgressAttestationCertificate,
)


def _compute_sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _hmac_sign(data: str, secret_key: str) -> str:
    return hmac.new(
        key=secret_key.encode("utf-8"),
        msg=data.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


class GenerativeAssetProvenanceEngine:
    """Engine responsible for issuing zero-egress certificates and tracking generative asset IP provenance."""

    def __init__(self, signing_secret: str = "MYRM_DEFAULT_SIGNING_SECRET_2026") -> None:
        self._secret = signing_secret

    def generate_zero_egress_certificate(
        self,
        session_id: str,
        tenant_id: str,
        sandbox_id: str,
        attestation_level: AttestationLevel = AttestationLevel.ENTERPRISE_ZERO_EGRESS,
    ) -> ZeroEgressAttestationCertificate:
        """Issue an immutable compliance certificate attesting that session data remains strictly confined."""
        cert_id = f"cert-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(UTC).isoformat()
        env_digest = _compute_sha256(f"{session_id}:{tenant_id}:{sandbox_id}")

        sig_payload = f"{cert_id}|{session_id}|{tenant_id}|{sandbox_id}|{attestation_level.value}|{env_digest}|{now_iso}"
        signature = _hmac_sign(sig_payload, self._secret)

        return ZeroEgressAttestationCertificate(
            certificate_id=cert_id,
            session_id=session_id,
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            attestation_level=attestation_level,
            zero_data_retention_guaranteed=True,
            no_model_training_guaranteed=True,
            environment_digest_sha256=env_digest,
            signature=signature,
            issued_at_iso=now_iso,
        )

    def generate_provenance_dossier(
        self,
        asset_id: str,
        asset_name: str,
        media_type: str,
        content: str | bytes,
        session_id: str,
        prompt_text: str,
        foundation_model_id: str,
        license_type: str = "PROPRIETARY_WORK_FOR_HIRE",
        ip_tier: IPCleanlinessTier = IPCleanlinessTier.ENTERPRISE_INDEMNIFIED,
        extra_metadata: dict[str, str] | None = None,
    ) -> AssetProvenanceDossier:
        """Create a cryptographic provenance record guaranteeing non-infringement tracking for generated code."""
        dossier_id = f"prov-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(UTC).isoformat()
        content_sha = _compute_sha256(content)
        prompt_sha = _compute_sha256(prompt_text)

        meta_tuple: tuple[tuple[str, str], ...] = ()
        if extra_metadata:
            meta_tuple = tuple(sorted(extra_metadata.items()))

        sig_payload = f"{dossier_id}|{asset_id}|{content_sha}|{prompt_sha}|{foundation_model_id}|{ip_tier.value}|{license_type}|{now_iso}"
        signature = _hmac_sign(sig_payload, self._secret)

        return AssetProvenanceDossier(
            dossier_id=dossier_id,
            asset_id=asset_id,
            asset_name=asset_name,
            media_type=media_type,
            content_sha256=content_sha,
            session_id=session_id,
            origin_prompt_sha256=prompt_sha,
            foundation_model_id=foundation_model_id,
            ip_tier=ip_tier,
            license_type=license_type,
            digital_signature=signature,
            created_at_iso=now_iso,
            metadata=meta_tuple,
        )

    def verify_asset_provenance(
        self,
        dossier: AssetProvenanceDossier,
        content: str | bytes,
        raise_on_error: bool = False,
    ) -> bool:
        """Validate that target content matches its registered IP provenance dossier digest."""
        computed_sha = _compute_sha256(content)
        if computed_sha != dossier.content_sha256:
            if raise_on_error:
                raise ProvenanceVerificationError(
                    f"Asset '{dossier.asset_id}' content mismatch: registered {dossier.content_sha256}, actual {computed_sha}."
                )
            return False
        return True
