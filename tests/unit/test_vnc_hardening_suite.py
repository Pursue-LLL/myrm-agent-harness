"""
[POS] tests/unit/test_vnc_hardening_suite.py
[INPUT] myrm_agent_harness.core.security.vnc_hardening
[OUTPUT] Unit tests for VncLoopbackBindAndRfbauthHardeningSuite
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.core.security.vnc_hardening import (
    VncBindMode,
    VncLaunchConfig,
    VncLoopbackBindAndRfbauthHardeningFacade,
    VncPasswdManager,
    VncSecurityError,
    VncSecurityViolationType,
)


@pytest.fixture
def facade() -> VncLoopbackBindAndRfbauthHardeningFacade:
    return VncLoopbackBindAndRfbauthHardeningFacade()


def test_default_loopback_and_localhost_injection(
    facade: VncLoopbackBindAndRfbauthHardeningFacade,
) -> None:
    config = VncLaunchConfig(
        display_num=2,
        vnc_port=5902,
        passwd_file="/tmp/vnc_pw_test",
        bind_mode=VncBindMode.LOOPBACK,
    )
    spec = facade.sanitize_launch_config(config)

    assert spec.is_hardened is True
    assert spec.effective_bind_mode == VncBindMode.LOOPBACK
    assert "-localhost" in spec.command_args
    assert "-nopw" not in spec.command_args
    assert "-rfbauth" in spec.command_args
    assert "/tmp/vnc_pw_test" in spec.command_args


def test_nopw_conflict_detection_and_remediation(
    facade: VncLoopbackBindAndRfbauthHardeningFacade,
) -> None:
    # 1. With auto-remediation (default)
    config = VncLaunchConfig(
        display_num=0,
        vnc_port=5900,
        passwd_file="/tmp/passwd",
        extra_flags=["-nopw", "-shared"],
    )
    spec = facade.sanitize_launch_config(config, auto_remediate=True)

    assert "-nopw" not in spec.command_args
    assert "-shared" in spec.command_args
    assert "-localhost" in spec.command_args
    assert len(spec.violations) == 1
    assert spec.violations[0].violation_type == VncSecurityViolationType.NOPW_CONFLICT
    assert spec.violations[0].auto_remediated is True

    # 2. Without auto-remediation -> raises VncSecurityError
    with pytest.raises(VncSecurityError, match="Conflicting '-nopw' flag detected"):
        facade.sanitize_launch_config(config, auto_remediate=False)


def test_non_loopback_opt_in_requires_flag_and_strong_password(
    facade: VncLoopbackBindAndRfbauthHardeningFacade,
) -> None:
    # 1. Request non-loopback without opt-in flag -> falls back to loopback
    cfg_unverified = VncLaunchConfig(
        display_num=1,
        vnc_port=5901,
        passwd_file="/tmp/passwd",
        bind_mode=VncBindMode.NON_LOOPBACK_OPT_IN,
        non_loopback_opt_in=False,
    )
    spec_unverified = facade.sanitize_launch_config(cfg_unverified)
    assert spec_unverified.effective_bind_mode == VncBindMode.LOOPBACK
    assert "-localhost" in spec_unverified.command_args
    assert any(
        v.violation_type == VncSecurityViolationType.UNPROTECTED_NON_LOOPBACK
        for v in spec_unverified.violations
    )

    # 2. Opt-in with weak password -> falls back to loopback
    cfg_weak = VncLaunchConfig(
        display_num=1,
        vnc_port=5901,
        passwd_file="/tmp/passwd",
        bind_mode=VncBindMode.NON_LOOPBACK_OPT_IN,
        non_loopback_opt_in=True,
        opt_in_password="simple",  # < 8 chars and no digit
    )
    spec_weak = facade.sanitize_launch_config(cfg_weak)
    assert spec_weak.effective_bind_mode == VncBindMode.LOOPBACK
    assert "-localhost" in spec_weak.command_args
    assert any(
        v.violation_type == VncSecurityViolationType.INSECURE_PASSWORD
        for v in spec_weak.violations
    )

    # 3. Proper opt-in with compliant strong password -> non-loopback allowed
    cfg_opted_in = VncLaunchConfig(
        display_num=1,
        vnc_port=5901,
        passwd_file="/tmp/passwd",
        bind_mode=VncBindMode.NON_LOOPBACK_OPT_IN,
        non_loopback_opt_in=True,
        opt_in_password="Secur3Password2026",
    )
    spec_opted_in = facade.sanitize_launch_config(cfg_opted_in)
    assert spec_opted_in.effective_bind_mode == VncBindMode.NON_LOOPBACK_OPT_IN
    assert "-localhost" not in spec_opted_in.command_args
    assert len(spec_opted_in.violations) == 0


def test_audit_raw_command(
    facade: VncLoopbackBindAndRfbauthHardeningFacade,
) -> None:
    # Insecure command missing -localhost and including -nopw
    insecure_cmd = ["x11vnc", "-display", ":0", "-rfbport", "5900", "-nopw"]
    report_insecure = facade.audit_raw_command(insecure_cmd)

    assert report_insecure.verdict == "BLOCKED"
    v_types = [v.violation_type for v in report_insecure.spec.violations]
    assert VncSecurityViolationType.NOPW_CONFLICT in v_types
    assert VncSecurityViolationType.UNPROTECTED_NON_LOOPBACK in v_types
    assert VncSecurityViolationType.MISSING_RFBAUTH in v_types

    # Compliant command
    compliant_cmd = [
        "x11vnc",
        "-display",
        ":0",
        "-rfbport",
        "5900",
        "-rfbauth",
        "/secure/pass",
        "-localhost",
    ]
    report_compliant = facade.audit_raw_command(compliant_cmd)
    assert report_compliant.verdict == "PASS"
    assert len(report_compliant.spec.violations) == 0


def test_passwd_manager_and_permission_hardening() -> None:
    mgr = VncPasswdManager()

    # Password generation and validation
    rand_pwd = mgr.generate_secure_password(16)
    assert len(rand_pwd) == 16
    is_valid, _ = mgr.evaluate_password_strength(rand_pwd)
    assert is_valid is True

    # Weak password validation
    is_v, reason = mgr.evaluate_password_strength("abc")
    assert is_v is False
    assert "at least 8" in reason

    is_v_num, _ = mgr.evaluate_password_strength("12345678")
    assert is_v_num is False

    # Permission inspection on temp file
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"secret")
        tmp_path = Path(f.name)

    try:
        # Make permissions overly permissive (0o666)
        tmp_path.chmod(0o666)
        ok, msg = mgr.inspect_and_harden_file_permissions(tmp_path)
        assert ok is True
        assert "hardened to 0600" in msg
        # File mode should now be 0600
        assert (tmp_path.stat().st_mode & 0o777) == 0o600
    finally:
        tmp_path.unlink(missing_ok=True)
