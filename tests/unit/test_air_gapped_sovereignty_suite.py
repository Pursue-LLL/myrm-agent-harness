"""
[POS] tests/unit/test_air_gapped_sovereignty_suite.py
[INPUT] myrm_agent_harness.core.security.air_gapped_sovereignty
[OUTPUT] Unit test suite for Air-Gapped Offline Trust Store & Sovereign Model Fallback Suite

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.air_gapped_sovereignty import (
    AirGappedSovereigntyFacade,
    EvidentiaryArchivePacker,
    ModelFallbackTarget,
    NetworkConnectivityModeEnum,
    OfflineTrustAnchor,
    OfflineTrustStore,
    SM3Hasher,
    SM4Cipher,
    SovereignModelFallbackManager,
    sm3_hash,
    sm4_decrypt_ecb,
    sm4_encrypt_ecb,
)


def test_gm_crypto_sm3_standard_vectors() -> None:
    """Test SM3 against standard GM/T 0004-2012 test vectors."""
    # Standard test vector 1: "abc"
    # Expected: 66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0
    digest_abc = sm3_hash("abc")
    assert digest_abc == "66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0"

    # Test empty string digest
    digest_empty = sm3_hash("")
    assert isinstance(digest_empty, str)
    assert len(digest_empty) == 64

    # Test bytes input
    digest_bytes = sm3_hash(b"hello world")
    assert SM3Hasher.hash("hello world") == digest_bytes


def test_gm_crypto_sm4_roundtrip() -> None:
    """Test SM4 block cipher encryption and decryption roundtrip."""
    key = b"0123456789abcdef"  # 16-byte key
    plaintext = b"Classified Payload: Agent Decision Protocol GM/T"

    ciphertext = sm4_encrypt_ecb(key, plaintext)
    assert ciphertext != plaintext
    assert len(ciphertext) % 16 == 0

    decrypted = sm4_decrypt_ecb(key, ciphertext)
    assert decrypted == plaintext

    cipher = SM4Cipher(key)
    block_enc = cipher.encrypt_block(b"0123456789ABCDEF")
    assert len(block_enc) == 16
    block_dec = cipher.decrypt_block(block_enc)
    assert block_dec == b"0123456789ABCDEF"


def test_offline_trust_store_validation_and_crl() -> None:
    """Test offline trust anchor evaluation and CRL revocation list."""
    store = OfflineTrustStore()
    now = time.time()

    # 1. Valid certificate issued by pre-distributed anchor
    res_valid = store.validate_certificate(
        cert_pem="CERT-AGENT-PROD-01",
        cert_serial="SN-10001",
        issuer_ca="GuizhouCA",
        valid_until=now + 86400,
        current_time=now,
    )
    assert res_valid.is_valid is True
    assert res_valid.is_revoked is False
    assert res_valid.ca_name == "GuizhouCA"

    # 2. Unknown Issuer CA
    res_unknown = store.validate_certificate(
        cert_pem="CERT-AGENT-ROGUE",
        cert_serial="SN-99999",
        issuer_ca="UnknownUntrustedCA",
        valid_until=now + 86400,
        current_time=now,
    )
    assert res_unknown.is_valid is False
    assert "not found in pre-distributed offline trust anchors" in res_unknown.reason

    # 3. Expired Certificate
    res_expired = store.validate_certificate(
        cert_pem="CERT-AGENT-EXPIRED",
        cert_serial="SN-10002",
        issuer_ca="NationalTimeServiceCenter",
        valid_until=now - 100,
        current_time=now,
    )
    assert res_expired.is_valid is False
    assert "Certificate expired" in res_expired.reason

    # 4. CRL Revocation check
    store.import_crl_bundle(["SN-10001"])
    res_revoked = store.validate_certificate(
        cert_pem="CERT-AGENT-PROD-01",
        cert_serial="SN-10001",
        issuer_ca="GuizhouCA",
        valid_until=now + 86400,
        current_time=now,
    )
    assert res_revoked.is_valid is False
    assert res_revoked.is_revoked is True
    assert "blacklisted in offline CRL" in res_revoked.reason


def test_sovereign_model_fallback_modes() -> None:
    """Test sovereign model routing under air-gapped, degraded, and online modes."""
    local_target = ModelFallbackTarget(
        model_id="deepseek-r1:70b-sovereign",
        endpoint_url="http://127.0.0.1:8000/v1",
        provider="vllm",
        is_local_sovereign=True,
    )
    manager = SovereignModelFallbackManager(
        initial_mode=NetworkConnectivityModeEnum.AIR_GAPPED_ISOLATED,
        default_sovereign_target=local_target,
    )

    # 1. In Air-Gapped mode, foreign remote models must divert to local sovereign
    target, was_fallback, reason = manager.resolve_effective_target("gpt-4o")
    assert was_fallback is True
    assert target.model_id == "deepseek-r1:70b-sovereign"
    assert "Air-gapped enforcement" in reason

    # 2. In Air-Gapped mode, registered local sovereign model directly succeeds
    target_local, was_fallback_l, _ = manager.resolve_effective_target("deepseek-r1:70b-sovereign")
    assert was_fallback_l is False
    assert target_local.model_id == "deepseek-r1:70b-sovereign"

    # 3. Switch to Online Mode and healthy remote
    manager.set_mode(NetworkConnectivityModeEnum.ONLINE)
    target_online, was_fallback_on, _ = manager.resolve_effective_target("gpt-4o", is_remote_healthy=True)
    assert was_fallback_on is False
    assert target_online.model_id == "gpt-4o"

    # 4. Online mode with remote unhealthy triggers failover
    target_degraded, was_fallback_deg, _ = manager.resolve_effective_target("gpt-4o", is_remote_healthy=False)
    assert was_fallback_deg is True
    assert target_degraded.model_id == "deepseek-r1:70b-sovereign"
    assert manager.get_mode() == NetworkConnectivityModeEnum.DEGRADED_FAILOVER


def test_evidentiary_archive_packer_tamper_evident() -> None:
    """Test tamper-evident evidentiary archive packaging and verification."""
    packer = EvidentiaryArchivePacker()
    records = [
        {"action": "SANDBOX_BOOT", "timestamp": "1775510000", "operator": "agent-01"},
        {"action": "EXECUTE_TOOL", "tool": "file_write", "target": "/data/audit.log"},
        {"action": "TERMINATE_SESSION", "exit_code": "0"},
    ]

    bundle = packer.pack_bundle(records, bundle_id="audit-bundle-test-01")
    assert bundle.bundle_id == "audit-bundle-test-01"
    assert bundle.record_count == 3
    assert len(bundle.sm3_root_digest) == 64

    # Verification matches
    assert packer.verify_bundle(bundle, records) is True

    # Tampered record fails verification
    tampered_records = list(records)
    tampered_records[1] = {"action": "EXECUTE_TOOL", "tool": "malicious_script", "target": "/etc/shadow"}
    assert packer.verify_bundle(bundle, tampered_records) is False

    # Count mismatch fails verification
    assert packer.verify_bundle(bundle, records[:2]) is False


def test_facade_end_to_end_and_metrics() -> None:
    """Test AirGappedSovereigntyFacade high-level operations and cumulative metrics."""
    facade = AirGappedSovereigntyFacade(mode=NetworkConnectivityModeEnum.AIR_GAPPED_ISOLATED)

    # Trust Anchor and Validation
    custom_ca = OfflineTrustAnchor(
        ca_name="EnterprisePrivateCA",
        root_cert_pem="CERT-PRIV-CA-DATA",
        valid_until=4102444800.0,
        fingerprint_sm3=sm3_hash("CERT-PRIV-CA-DATA"),
    )
    facade.add_trust_anchor(custom_ca)
    assert len(facade.list_trust_anchors()) == 4

    # Validation
    val_res = facade.validate_offline_certificate(
        cert_pem="CERT-CLIENT-001",
        cert_serial="SN-CLIENT-001",
        issuer_ca="EnterprisePrivateCA",
        valid_until=4102444800.0,
    )
    assert val_res.is_valid is True

    # Model Fallback
    target, was_fallback, _ = facade.resolve_model("claude-3-opus")
    assert was_fallback is True
    assert target.is_local_sovereign is True

    # Evidentiary bundle seal
    bundle = facade.seal_audit_bundle([{"event": "system_boot"}])
    assert bundle.record_count == 1
    assert facade.verify_audit_bundle(bundle, [{"event": "system_boot"}]) is True

    # Metrics
    metrics = facade.get_metrics()
    assert metrics.total_offline_validations == 1
    assert metrics.valid_certificates_count == 1
    assert metrics.model_fallback_events == 1
    assert metrics.audit_bundles_sealed == 1
