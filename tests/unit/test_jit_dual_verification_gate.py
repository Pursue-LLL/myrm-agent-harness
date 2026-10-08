"""Unit tests for JIT Dual Verification Gate Suite.

[POS]
Tests immutable content fingerprint computation, metadata short-circuit evaluation,
deep SHA-256 comparison, and dual dynamic assertions guarding against TOCTOU tampering.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from myrm_agent_harness.agent.security.jit_gate import (
    AssetContentFingerprint,
    AssetTamperedDuringApprovalError,
    AssetType,
    JITDualVerificationGate,
    PolicyTightenedAtJITError,
)


def test_file_fingerprint_computation_and_lf_normalization(tmp_path: Path) -> None:
    """Ensure file fingerprint computation normalizes CRLF to LF to prevent false alarms."""
    test_file = tmp_path / "script.sh"
    test_file.write_bytes(b"echo hello\r\nworld\r\n")

    fp1 = JITDualVerificationGate.compute_file_fingerprint(test_file)
    assert fp1.asset_type == AssetType.FILE
    assert fp1.st_size == len(b"echo hello\r\nworld\r\n")
    assert fp1.content_sha256 != ""

    # Write LF content
    test_file.write_bytes(b"echo hello\nworld\n")
    fp2 = JITDualVerificationGate.compute_file_fingerprint(test_file)

    # Hash should match due to LF normalization
    assert fp1.content_sha256 == fp2.content_sha256


def test_command_fingerprint_deterministic_canonicalization() -> None:
    """Ensure structured commands produce canonical deterministic fingerprints."""
    fp1 = JITDualVerificationGate.compute_command_fingerprint("  rm   -rf   /tmp/data  ", "bash")
    fp2 = JITDualVerificationGate.compute_command_fingerprint("rm -rf /tmp/data", "bash")
    assert fp1.content_sha256 == fp2.content_sha256
    assert fp1.asset_type == AssetType.COMMAND


def test_fast_metadata_short_circuit_and_deep_sha256(tmp_path: Path) -> None:
    """Verify level 1 fast metadata short-circuit and level 2 deep SHA comparison."""
    target_file = tmp_path / "app.py"
    target_file.write_text("print('safe')", encoding="utf-8")

    fp = JITDualVerificationGate.compute_file_fingerprint(target_file)

    # Fast metadata match
    res = JITDualVerificationGate.verify_physical_asset_untampered(fp, target_file)
    assert res.is_valid is True
    assert res.details.get("short_circuit_metadata_match") is True

    # Artificially alter file content while mocking metadata mismatch
    time.sleep(0.01)
    target_file.write_text("print('malicious backdoor')", encoding="utf-8")

    res_tampered = JITDualVerificationGate.verify_physical_asset_untampered(fp, target_file)
    assert res_tampered.is_valid is False
    assert "Content SHA-256 mismatch" in (res_tampered.failure_reason or "")
    assert res_tampered.current_sha256 != fp.content_sha256


def test_assert_jit_dual_verification_tampering_and_policy(tmp_path: Path) -> None:
    """Ensure JIT assertions strictly block tampered files and tightened policies."""
    target_file = tmp_path / "config.json"
    target_file.write_text('{"mode": "safe"}', encoding="utf-8")

    fp = JITDualVerificationGate.compute_file_fingerprint(target_file)

    # Valid execution instant passes without error
    JITDualVerificationGate.assert_jit_dual_verification(
        fingerprint=fp,
        target_path=target_file,
        is_policy_allowed=True,
    )

    # Tamper the file
    target_file.write_text('{"mode": "compromised"}', encoding="utf-8")

    with pytest.raises(AssetTamperedDuringApprovalError) as exc_info:
        JITDualVerificationGate.assert_jit_dual_verification(
            fingerprint=fp,
            target_path=target_file,
            is_policy_allowed=True,
        )
    assert "TOCTOU violation detected" in str(exc_info.value)

    # Test policy tightened at execution moment
    with pytest.raises(PolicyTightenedAtJITError) as exc_info2:
        JITDualVerificationGate.assert_jit_dual_verification(
            fingerprint=fp,
            target_path=target_file,
            is_policy_allowed=False,
            policy_disallow_reason="Action disallowed by admin policy change",
        )
    assert "Action disallowed by admin policy change" in str(exc_info2.value)
