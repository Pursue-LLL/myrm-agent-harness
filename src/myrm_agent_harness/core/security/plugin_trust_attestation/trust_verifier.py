"""Plugin Trust Chain Verifier and Dynamic Capability Attestation Engine.

Implements cryptographic signature generation and verification for official vetted pipelines,
as well as dynamic capability attestation tokens guarding runtime sandbox execution.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time

from myrm_agent_harness.core.security.plugin_trust_attestation.types import (
    CapabilityAttestationToken,
    PluginCapabilityManifest,
    PluginSignaturePackage,
    PluginTrustTier,
    VerificationOutcome,
)

logger = logging.getLogger(__name__)

# Default master signing key for pipeline attestation verification
_DEFAULT_SIGNING_SECRET: bytes = b"myrm-official-plugin-root-ca-key-v1"


class PluginTrustChainVerifier:
    """Verifier governing release cryptographic signatures and runtime capability attestations."""

    def __init__(self, signing_secret: bytes | None = None) -> None:
        self._signing_secret: bytes = signing_secret or _DEFAULT_SIGNING_SECRET

    @staticmethod
    def compute_payload_digest(files: dict[str, str]) -> str:
        """Compute deterministic SHA-256 digest of a plugin's code and manifest files."""
        hasher = hashlib.sha256()
        # Sort by filename to guarantee canonical reproducibility
        for filename in sorted(files.keys()):
            hasher.update(filename.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(files[filename].encode("utf-8"))
            hasher.update(b"\x00")
        return hasher.hexdigest()

    def sign_plugin_package(
        self,
        plugin_id: str,
        version: str,
        payload_sha256: str,
        trust_tier: PluginTrustTier,
        signer_identity: str = "myrm-official-ca",
    ) -> PluginSignaturePackage:
        """Generate official digital release signature for a vetted plugin package."""
        timestamp = time.time()
        message = f"{plugin_id}:{version}:{payload_sha256}:{trust_tier.value}:{signer_identity}:{int(timestamp)}"
        signature = hmac.new(
            self._signing_secret,
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return PluginSignaturePackage(
            plugin_id=plugin_id,
            version=version,
            payload_sha256=payload_sha256,
            signature=signature,
            signer_identity=signer_identity,
            trust_tier=trust_tier,
            signed_at=timestamp,
        )

    def verify_package(
        self,
        package: PluginSignaturePackage,
        actual_payload_sha256: str,
    ) -> VerificationOutcome:
        """Verify the integrity, signature, and trust tier of a plugin package.

        Fail-closed:
        - If payload SHA-256 does not match, reject as tampered.
        - If signature fails HMAC verification, reject as untrusted.
        - If trust tier is COMPROMISED_REVOKED, reject immediately.
        """
        if package.trust_tier == PluginTrustTier.COMPROMISED_REVOKED:
            return VerificationOutcome(
                is_valid=False,
                trust_tier=package.trust_tier,
                error_message="Plugin is marked COMPROMISED_REVOKED and cannot be verified.",
            )

        # Integrity check
        if not hmac.compare_digest(package.payload_sha256, actual_payload_sha256):
            return VerificationOutcome(
                is_valid=False,
                trust_tier=package.trust_tier,
                error_message="Payload SHA-256 mismatch: plugin package has been tampered with.",
            )

        # Signature verification
        message = (
            f"{package.plugin_id}:{package.version}:{package.payload_sha256}:"
            f"{package.trust_tier.value}:{package.signer_identity}:{int(package.signed_at)}"
        )
        expected_sig = hmac.new(
            self._signing_secret,
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(package.signature, expected_sig):
            return VerificationOutcome(
                is_valid=False,
                trust_tier=package.trust_tier,
                error_message="Cryptographic signature verification failed: invalid publisher signature.",
            )

        return VerificationOutcome(
            is_valid=True,
            trust_tier=package.trust_tier,
            error_message=None,
        )

    def issue_attestation_token(
        self,
        manifest: PluginCapabilityManifest,
        validity_seconds: int = 3600,
    ) -> CapabilityAttestationToken:
        """Issue a time-bound dynamic capability attestation token for runtime sandbox isolation."""
        now = time.time()
        token_id = f"attest-{secrets.token_hex(8)}"
        expires_at = now + validity_seconds

        token_body = json.dumps(
            {
                "token_id": token_id,
                "plugin_id": manifest.plugin_id,
                "domains": sorted(manifest.network_domains),
                "file_scope": manifest.file_access_scope,
                "shell": manifest.allow_shell_exec,
                "issued_at": int(now),
                "expires_at": int(expires_at),
            },
            sort_keys=True,
        )
        token_hmac = hmac.new(
            self._signing_secret,
            token_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return CapabilityAttestationToken(
            token_id=token_id,
            plugin_id=manifest.plugin_id,
            granted_domains=list(manifest.network_domains),
            granted_file_scope=manifest.file_access_scope,
            allow_shell=manifest.allow_shell_exec,
            issued_at=now,
            expires_at=expires_at,
            token_hmac=token_hmac,
        )

    def verify_operation_permission(
        self,
        token: CapabilityAttestationToken,
        target_domain: str | None = None,
        requires_shell: bool = False,
    ) -> bool:
        """Evaluate whether an attempted runtime action is permitted by the attestation token."""
        now = time.time()
        if now > token.expires_at:
            logger.warning("Attestation token '%s' has expired.", token.token_id)
            return False

        # Re-verify token authenticity
        token_body = json.dumps(
            {
                "token_id": token.token_id,
                "plugin_id": token.plugin_id,
                "domains": sorted(token.granted_domains),
                "file_scope": token.granted_file_scope,
                "shell": token.allow_shell,
                "issued_at": int(token.issued_at),
                "expires_at": int(token.expires_at),
            },
            sort_keys=True,
        )
        expected_hmac = hmac.new(
            self._signing_secret,
            token_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(token.token_hmac, expected_hmac):
            logger.error("Attestation token HMAC verification failed.")
            return False

        # Shell execution constraint
        if requires_shell and not token.allow_shell:
            logger.warning("Plugin '%s' attempted shell exec without attestation permission.", token.plugin_id)
            return False

        # Network domain constraint
        if target_domain and target_domain not in token.granted_domains:
            logger.warning(
                "Plugin '%s' attempted outbound connect to un-attested domain: '%s'.",
                token.plugin_id,
                target_domain,
            )
            return False

        return True
