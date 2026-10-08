"""Unit tests for Vetted Plugin Registry Trust Chain and Dynamic Capability Attestation Suite."""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.plugin_trust_attestation.trust_verifier import (
    PluginTrustChainVerifier,
)
from myrm_agent_harness.core.security.plugin_trust_attestation.types import (
    CapabilityAttestationToken,
    PluginCapabilityManifest,
    PluginSignaturePackage,
    PluginTrustTier,
)


def test_payload_digest_deterministic() -> None:
    files_a: dict[str, str] = {
        "index.py": "print('hello')",
        "manifest.json": '{"name": "calc"}',
    }
    files_b: dict[str, str] = {
        "manifest.json": '{"name": "calc"}',
        "index.py": "print('hello')",
    }
    digest_a = PluginTrustChainVerifier.compute_payload_digest(files_a)
    digest_b = PluginTrustChainVerifier.compute_payload_digest(files_b)
    assert digest_a == digest_b
    assert len(digest_a) == 64

    # Tampered content results in different digest
    files_tampered: dict[str, str] = {
        "index.py": "print('hello tampered')",
        "manifest.json": '{"name": "calc"}',
    }
    digest_tampered = PluginTrustChainVerifier.compute_payload_digest(files_tampered)
    assert digest_tampered != digest_a


def test_sign_and_verify_valid_package() -> None:
    verifier = PluginTrustChainVerifier()
    plugin_id = "org.myrm.calculator"
    version = "1.0.0"
    payload_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    pkg = verifier.sign_plugin_package(
        plugin_id=plugin_id,
        version=version,
        payload_sha256=payload_sha256,
        trust_tier=PluginTrustTier.OFFICIAL_VERIFIED,
    )

    assert pkg.plugin_id == plugin_id
    assert pkg.version == version
    assert pkg.trust_tier == PluginTrustTier.OFFICIAL_VERIFIED

    outcome = verifier.verify_package(pkg, payload_sha256)
    assert outcome.is_valid is True
    assert outcome.trust_tier == PluginTrustTier.OFFICIAL_VERIFIED
    assert outcome.error_message is None


def test_verify_package_tampered_payload_rejected() -> None:
    verifier = PluginTrustChainVerifier()
    pkg = verifier.sign_plugin_package(
        plugin_id="org.myrm.sandbox",
        version="2.0.0",
        payload_sha256="original_hash_1234567890abcdef",
        trust_tier=PluginTrustTier.VETTED_COMMUNITY,
    )

    tampered_hash = "tampered_hash_0987654321fedcba"
    outcome = verifier.verify_package(pkg, tampered_hash)
    assert outcome.is_valid is False
    assert "Payload SHA-256 mismatch" in (outcome.error_message or "")


def test_verify_package_invalid_signature_rejected() -> None:
    verifier = PluginTrustChainVerifier(signing_secret=b"valid-key")
    attacker_verifier = PluginTrustChainVerifier(signing_secret=b"attacker-key")

    malicious_pkg = attacker_verifier.sign_plugin_package(
        plugin_id="org.myrm.malicious",
        version="0.1.0",
        payload_sha256="payload_hash_11223344",
        trust_tier=PluginTrustTier.OFFICIAL_VERIFIED,
    )

    outcome = verifier.verify_package(malicious_pkg, "payload_hash_11223344")
    assert outcome.is_valid is False
    assert "Cryptographic signature verification failed" in (outcome.error_message or "")


def test_verify_package_revoked_tier_rejected() -> None:
    verifier = PluginTrustChainVerifier()
    revoked_pkg = PluginSignaturePackage(
        plugin_id="org.myrm.exploit",
        version="0.0.1",
        payload_sha256="hash123",
        signature="sig123",
        signer_identity="attacker",
        trust_tier=PluginTrustTier.COMPROMISED_REVOKED,
        signed_at=time.time(),
    )

    outcome = verifier.verify_package(revoked_pkg, "hash123")
    assert outcome.is_valid is False
    assert "COMPROMISED_REVOKED" in (outcome.error_message or "")


def test_issue_attestation_token_and_runtime_verification() -> None:
    verifier = PluginTrustChainVerifier()
    manifest = PluginCapabilityManifest(
        plugin_id="org.myrm.fetcher",
        version="1.0.0",
        network_domains=["api.github.com", "api.openai.com"],
        file_access_scope="WORKSPACE_ONLY",
        allow_shell_exec=False,
    )

    token = verifier.issue_attestation_token(manifest, validity_seconds=300)
    assert token.plugin_id == "org.myrm.fetcher"
    assert token.allow_shell is False
    assert "api.github.com" in token.granted_domains

    # Permitted network call
    assert (
        verifier.verify_operation_permission(
            token=token,
            target_domain="api.github.com",
            requires_shell=False,
        )
        is True
    )

    # Denied unauthorized outbound domain
    assert (
        verifier.verify_operation_permission(
            token=token,
            target_domain="malicious-c2.attacker.com",
            requires_shell=False,
        )
        is False
    )

    # Denied shell execution without permission
    assert (
        verifier.verify_operation_permission(
            token=token,
            target_domain=None,
            requires_shell=True,
        )
        is False
    )


def test_verify_operation_tampered_token_rejected() -> None:
    verifier = PluginTrustChainVerifier()
    manifest = PluginCapabilityManifest(
        plugin_id="org.myrm.agent",
        version="1.0.0",
        network_domains=["example.com"],
        allow_shell_exec=False,
    )
    token = verifier.issue_attestation_token(manifest, validity_seconds=300)

    # Attacker attempts privilege escalation by altering allow_shell to True
    tampered_token = CapabilityAttestationToken(
        token_id=token.token_id,
        plugin_id=token.plugin_id,
        granted_domains=token.granted_domains,
        granted_file_scope=token.granted_file_scope,
        allow_shell=True,  # escalated!
        issued_at=token.issued_at,
        expires_at=token.expires_at,
        token_hmac=token.token_hmac,
    )

    assert verifier.verify_operation_permission(tampered_token, requires_shell=True) is False


def test_verify_operation_expired_token_rejected() -> None:
    verifier = PluginTrustChainVerifier()
    manifest = PluginCapabilityManifest(
        plugin_id="org.myrm.agent",
        version="1.0.0",
        network_domains=["example.com"],
        allow_shell_exec=True,
    )
    # Token expired 10 seconds ago
    token = verifier.issue_attestation_token(manifest, validity_seconds=-10)

    assert verifier.verify_operation_permission(token, requires_shell=False) is False
