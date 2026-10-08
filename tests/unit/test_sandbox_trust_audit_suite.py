"""Unit tests for Sandbox Trust Transparency and Security Isolation Audit Card Suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.sandbox_trust_audit import (
    IsolationLevel,
    ProbeCheckStatus,
    SandboxHealthSelfAuditProbe,
    SandboxTrustAuditCardEngine,
    TrustGrade,
)


def test_probe_clean_environment_passes() -> None:
    """Verify that a properly contained sandbox passes all self-audit checks with score 100."""
    probe = SandboxHealthSelfAuditProbe()
    report = probe.run_audit(
        environment_id="env_clean_01",
        isolation_level=IsolationLevel.CLOUD_DEDICATED_SANDBOX,
        mounted_paths=["/workspace", "/tmp/sandbox", "/mnt/volumes/user1/persistent"],
        env_vars={"NODE_ENV": "production", "APP_PORT": "3000"},
        is_root=False,
        egress_monitored=True,
    )
    assert report.passed is True
    assert report.score == 100
    assert len(report.checks) == 4
    assert all(c.status == ProbeCheckStatus.PASS for c in report.checks)


def test_probe_critical_host_path_leak() -> None:
    """Verify probe catches accidental exposure of sensitive host directories."""
    probe = SandboxHealthSelfAuditProbe()
    report = probe.run_audit(
        environment_id="env_leaky_fs",
        isolation_level=IsolationLevel.LOCAL_RESTRICTED_CONTAINER,
        mounted_paths=["/workspace", "~/.ssh", "/var/run/docker.sock"],
    )
    assert report.passed is False
    assert report.score <= 60
    fs_check = next(c for c in report.checks if c.check_id == "FS_01")
    assert fs_check.status == ProbeCheckStatus.FAIL
    assert "~/.ssh" in fs_check.details


def test_probe_sensitive_env_leak() -> None:
    """Verify probe flags raw API keys and cloud credentials in environment variables."""
    probe = SandboxHealthSelfAuditProbe()
    report = probe.run_audit(
        environment_id="env_secret_leak",
        isolation_level=IsolationLevel.CLOUD_DEDICATED_SANDBOX,
        env_vars={
            "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "OPENAI_API_KEY": "sk-proj-1234567890",
        },
    )
    assert report.passed is False
    env_check = next(c for c in report.checks if c.check_id == "ENV_01")
    assert env_check.status == ProbeCheckStatus.FAIL
    assert "AWS_SECRET_ACCESS_KEY" in env_check.details


def test_probe_unmonitored_network_egress() -> None:
    """Verify probe fails when outbound network traffic is not screened by Sentinel."""
    probe = SandboxHealthSelfAuditProbe()
    report = probe.run_audit(
        environment_id="env_no_sentinel",
        isolation_level=IsolationLevel.CLOUD_DEDICATED_SANDBOX,
        egress_monitored=False,
    )
    assert report.passed is False
    net_check = next(c for c in report.checks if c.check_id == "NET_01")
    assert net_check.status == ProbeCheckStatus.FAIL


def test_audit_card_engine_badge_generation() -> None:
    """Verify trust badges across isolation tiers and audit scores."""
    engine = SandboxTrustAuditCardEngine()

    # 1. Cloud dedicated (score 100)
    badge_cloud = engine.generate_badge(
        isolation_level=IsolationLevel.CLOUD_DEDICATED_SANDBOX,
        audit_score=100,
    )
    assert badge_cloud.trust_grade == TrustGrade.MAXIMUM_ISOLATION
    assert badge_cloud.color_hex == "#10B981"
    assert "云托管专属沙箱" in badge_cloud.badge_label

    # 2. Local restricted container
    badge_local = engine.generate_badge(
        isolation_level=IsolationLevel.LOCAL_RESTRICTED_CONTAINER,
        audit_score=85,
    )
    assert badge_local.trust_grade == TrustGrade.RESTRICTED_SANDBOXED
    assert badge_local.color_hex == "#6366F1"

    # 3. Host direct unconfined
    badge_host = engine.generate_badge(
        isolation_level=IsolationLevel.HOST_DIRECT_FULL_TRUST,
        audit_score=50,
    )
    assert badge_host.trust_grade == TrustGrade.UNCONFINED_HOST
    assert badge_host.color_hex == "#F59E0B"


def test_audit_card_engine_boundary_card() -> None:
    """Verify permission hot-boundary card construction and denial list inclusion."""
    engine = SandboxTrustAuditCardEngine()
    card = engine.generate_boundary_card(
        environment_id="env_prod_01",
        isolation_level=IsolationLevel.CLOUD_DEDICATED_SANDBOX,
        allowed_paths=["/workspace", "/tmp/sandbox"],
    )
    assert card.environment_id == "env_prod_01"
    assert "/workspace" in card.allowed_paths
    assert "~/.ssh" in card.denied_paths
    assert "/etc/shadow" in card.denied_paths
    assert len(card.active_guards) >= 3
    assert "Sentinel" in card.egress_policy
