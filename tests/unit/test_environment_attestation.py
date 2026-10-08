"""Unit tests for Runtime Environment and Connection Integrity Attestation Suite.

[POS]
Validates host architecture probing, mount penetration audits, binary SHA-256 integrity,
all-vector pre-flight reporting, and critical anomaly hard-break shutdowns.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from myrm_agent_harness.agent.security.attestation import (
    AttestationConfig,
    AttestationFailedHardBreakError,
    BinaryIntegrityProbe,
    EnvironmentAttestationEngine,
    HostIsolationProbe,
    VectorCategory,
)


def test_host_isolation_and_mount_probes() -> None:
    """Ensure host isolation and dangerous mount probes generate structured check results."""
    # 1. Host architecture probe
    host_res = HostIsolationProbe.audit_host_fingerprint()
    assert host_res.vector == VectorCategory.HOST_ISOLATION
    assert host_res.is_valid is True
    assert host_res.actual_digest is not None

    # 2. Mount boundary audit
    mount_results = HostIsolationProbe.audit_dangerous_mounts()
    assert len(mount_results) >= 3
    for r in mount_results:
        assert r.vector == VectorCategory.MOUNT_BOUNDARY
        assert "exists" in r.details


def test_binary_integrity_probe_success_and_tamper_detection(tmp_path: Path) -> None:
    """Ensure binary integrity probe catches SHA-256 tampering and missing files."""
    valid_bin = tmp_path / "valid_tool.py"
    valid_bin.write_bytes(b"#!/usr/bin/env python\nprint('legit')")

    actual_sha = BinaryIntegrityProbe.compute_file_sha256(valid_bin)

    # 1. Matching binary passes
    res_valid = BinaryIntegrityProbe.verify_binary(valid_bin, actual_sha)
    assert res_valid.is_valid is True
    assert res_valid.actual_digest == actual_sha

    # 2. Tampered binary fails
    tampered_sha = "0000000000000000000000000000000000000000000000000000000000000000"
    res_tampered = BinaryIntegrityProbe.verify_binary(valid_bin, tampered_sha)
    assert res_tampered.is_valid is False
    assert "tampering detected" in (res_tampered.error_message or "").lower()

    # 3. Missing binary fails
    missing_bin = tmp_path / "non_existent.sh"
    res_missing = BinaryIntegrityProbe.verify_binary(missing_bin)
    assert res_missing.is_valid is False
    assert "missing" in (res_missing.error_message or "").lower()


def test_environment_attestation_engine_all_vectors_and_hard_break(tmp_path: Path) -> None:
    """Ensure attestation engine generates report and enforces hard-break on critical anomaly."""
    safe_file = tmp_path / "core_runner.py"
    safe_file.write_text("print('safe')", encoding="utf-8")
    safe_sha = BinaryIntegrityProbe.compute_file_sha256(safe_file)

    config = AttestationConfig(
        check_mounts=True,
        binaries={safe_file: safe_sha},
    )

    # 1. Clean audit passes
    report = EnvironmentAttestationEngine.run_preflight_audit(config)
    assert report.attestation_id.startswith("attest-")
    assert report.overall_passed is True
    assert len(report.vector_results) >= 2

    # 2. Assert passes cleanly
    assert_report = EnvironmentAttestationEngine.assert_attestation_passed(config)
    assert assert_report.overall_passed is True

    # 3. Inject critical tampering anomaly into config
    compromised_config = AttestationConfig(
        check_mounts=True,
        binaries={safe_file: "forged_sha256_hash_here"},
    )

    # Preflight records failure
    failing_report = EnvironmentAttestationEngine.run_preflight_audit(compromised_config)
    assert failing_report.overall_passed is False
    assert len(failing_report.failed_critical_vectors) == 1

    # Assert raises hard-break error
    with pytest.raises(AttestationFailedHardBreakError) as exc_info:
        EnvironmentAttestationEngine.assert_attestation_passed(compromised_config)
    assert "Runtime environment integrity compromised" in str(exc_info.value)
    assert f"binary_integrity:{safe_file.resolve()}" in exc_info.value.failed_vectors
