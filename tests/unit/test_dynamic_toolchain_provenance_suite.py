"""
Unit tests for Dynamic Toolchain Supply Chain Provenance & Pre-Install Sandbox Hardening Suite.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.dynamic_toolchain_provenance import (
    ASTViolationType,
    DynamicToolchainProvenanceSuite,
    JITSandboxConfiner,
    PreInstallASTScanner,
    ProvenanceStatus,
    ProvenanceVerificationGate,
    SkillProvenanceManifest,
)


def test_provenance_verification_gate() -> None:
    verifier = ProvenanceVerificationGate()
    code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    code_sha = verifier.compute_sha256(code)
    valid_sig = verifier.generate_valid_signature("myrm-official", code_sha)

    # 1. Successful verification
    manifest_valid = SkillProvenanceManifest(
        skill_id="calculator",
        version="1.0.0",
        publisher_id="myrm-official",
        source_sha256=code_sha,
        signature=valid_sig,
    )
    status, _ = verifier.verify_provenance(code, manifest_valid)
    assert status == ProvenanceStatus.VERIFIED

    # 2. Untrusted publisher
    manifest_untrusted = SkillProvenanceManifest(
        skill_id="calculator",
        version="1.0.0",
        publisher_id="malicious-actor",
        source_sha256=code_sha,
        signature=valid_sig,
    )
    status, _ = verifier.verify_provenance(code, manifest_untrusted)
    assert status == ProvenanceStatus.UNTRUSTED_PUBLISHER

    # 3. Hash mismatch (tampered code)
    tampered_code = code + "\n# backdoor\n"
    status, _ = verifier.verify_provenance(tampered_code, manifest_valid)
    assert status == ProvenanceStatus.HASH_MISMATCH

    # 4. Invalid signature
    manifest_bad_sig = SkillProvenanceManifest(
        skill_id="calculator",
        version="1.0.0",
        publisher_id="myrm-official",
        source_sha256=code_sha,
        signature="invalid_sig_hex",
    )
    status, _ = verifier.verify_provenance(code, manifest_bad_sig)
    assert status == ProvenanceStatus.SIGNATURE_INVALID

    # 5. Dynamic publisher registration
    verifier.register_trusted_publisher("custom-org")
    assert verifier.is_publisher_trusted("custom-org") is True
    verifier.revoke_trusted_publisher("custom-org")
    assert verifier.is_publisher_trusted("custom-org") is False


def test_pre_install_ast_scanner_clean_and_violations() -> None:
    scanner = PreInstallASTScanner()

    # 1. Clean code
    clean_code = """
def parse_metrics(data: str) -> list[int]:
    return [len(x) for x in data.split(',')]
"""
    clean_findings = scanner.scan_source_code(clean_code, skill_id="clean-parser")
    assert len(clean_findings) == 0

    # 2. Dangerous exec (eval)
    eval_code = "eval('__import__(\"os\").system(\"whoami\")')"
    eval_findings = scanner.scan_source_code(eval_code)
    types = {f.violation_type for f in eval_findings}
    assert ASTViolationType.DANGEROUS_EXEC in types

    # 3. Process spawn (subprocess.run)
    proc_code = """
import subprocess
def run_cmd():
    subprocess.run(['rm', '-rf', '/tmp'])
"""
    proc_findings = scanner.scan_source_code(proc_code)
    assert any(f.violation_type == ASTViolationType.PROCESS_SPAWN for f in proc_findings)

    # 4. Raw socket
    socket_code = """
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
"""
    socket_findings = scanner.scan_source_code(socket_code)
    assert any(f.violation_type == ASTViolationType.UNDECLARED_SOCKET for f in socket_findings)

    # 5. Credential probe
    env_probe_code = """
import os
key = os.environ['OPENAI_API_KEY']
"""
    env_findings = scanner.scan_source_code(env_probe_code)
    assert any(f.violation_type == ASTViolationType.ENV_CREDENTIAL_PROBE for f in env_findings)


def test_jit_sandbox_confiner() -> None:
    confiner = JITSandboxConfiner()

    manifest = SkillProvenanceManifest(
        skill_id="web-fetcher",
        version="2.0.0",
        publisher_id="myrm-official",
        source_sha256="dummy-sha",
        signature="dummy-sig",
        declared_domains=["api.github.com", "crates.io"],
        declared_paths=["/workspace/cache", "/etc/shadow", "~/.ssh/id_rsa"],
        declared_env_keys=["GITHUB_TOKEN", "CACHE_TTL_SECONDS"],
    )

    policy = confiner.issue_confinement_policy(manifest)
    assert policy.skill_id == "web-fetcher"
    assert policy.is_confined is True

    # Check forbidden paths stripped
    assert "/workspace/cache" in policy.allowed_paths
    assert "/etc/shadow" not in policy.allowed_paths
    assert "~/.ssh/id_rsa" not in policy.allowed_paths

    # Check forbidden env secrets stripped
    assert "CACHE_TTL_SECONDS" in policy.allowed_env_keys
    assert "GITHUB_TOKEN" not in policy.allowed_env_keys

    # Check permission evaluation helpers
    assert confiner.is_network_call_permitted(policy, "api.github.com") is True
    assert confiner.is_network_call_permitted(policy, "sub.crates.io") is True
    assert confiner.is_network_call_permitted(policy, "evil-exfiltration.com") is False

    assert confiner.is_path_access_permitted(policy, "/workspace/cache/temp.json") is True
    assert confiner.is_path_access_permitted(policy, "/var/run/docker.sock") is False

    assert confiner.is_env_access_permitted(policy, "CACHE_TTL_SECONDS") is True
    assert confiner.is_env_access_permitted(policy, "GITHUB_TOKEN") is False


def test_dynamic_toolchain_provenance_suite_facade() -> None:
    suite = DynamicToolchainProvenanceSuite()

    # 1. Clean approved skill flow
    clean_code = "def format_text(s: str) -> str:\n    return s.strip().title()\n"
    code_sha = suite._verifier.compute_sha256(clean_code)
    valid_sig = suite.generate_valid_signature("myrm-official", code_sha)

    manifest = SkillProvenanceManifest(
        skill_id="text-formatter",
        version="1.0.0",
        publisher_id="myrm-official",
        source_sha256=code_sha,
        signature=valid_sig,
        declared_domains=["api.dictionary.org"],
        declared_paths=["/workspace/out"],
        declared_env_keys=["FORMAT_LOCALE"],
    )

    decision = suite.evaluate_and_install_skill(clean_code, manifest)
    assert decision.is_installation_approved is True
    assert decision.is_provenance_valid is True
    assert decision.is_ast_clean is True
    assert decision.confinement_policy is not None
    assert suite.metrics.installations_approved_total == 1
    assert suite.metrics.confinements_issued_total == 1

    # 2. Blocked by AST violation
    malicious_code = "import os\ndef pwn():\n    os.system('id')\n"
    mal_sha = suite._verifier.compute_sha256(malicious_code)
    mal_sig = suite.generate_valid_signature("myrm-official", mal_sha)

    manifest_mal = SkillProvenanceManifest(
        skill_id="trojan-helper",
        version="1.0.0",
        publisher_id="myrm-official",
        source_sha256=mal_sha,
        signature=mal_sig,
    )

    decision_mal = suite.evaluate_and_install_skill(malicious_code, manifest_mal)
    assert decision_mal.is_installation_approved is False
    assert decision_mal.is_ast_clean is False
    assert len(decision_mal.ast_findings) >= 1
    assert suite.metrics.installations_blocked_total == 1
    assert suite.metrics.ast_violations_detected_total >= 1
