"""Unit tests for Multi-Tenant Data Isolation and Cross-Contamination Probes."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.data_isolation_probes import (
    CrossTenantProbeRunner,
    MemoryNamespaceFirewall,
    TenantMemoryContext,
)


def test_memory_namespace_firewall_compilation_and_sanitization() -> None:
    """Test partition key compilation and malicious query injection stripping."""
    firewall = MemoryNamespaceFirewall()

    # 1. Clean tenant context
    ctx = TenantMemoryContext(
        user_id="user_alice",
        agent_id="agent_coder",
        scope="agent",
    )
    spec = firewall.compile_partition_key(ctx)
    assert spec.composite_key == "usr_user_alice::agt_agent_coder::scp_agent"
    assert len(spec.namespace_digest) == 16
    assert spec.user_id == "user_alice"

    # 2. Malicious injection attempt in user_id is sanitized
    nasty_ctx = TenantMemoryContext(
        user_id="admin' OR 1=1 --",
        agent_id="agent_coder",
    )
    nasty_spec = firewall.compile_partition_key(nasty_ctx)
    assert "'" not in nasty_spec.user_id
    assert "--" not in nasty_spec.user_id
    assert "OR" not in nasty_spec.user_id

    # 3. Empty identifier raises ValueError
    empty_ctx = TenantMemoryContext(user_id="", agent_id="agent_1")
    with pytest.raises(ValueError, match="cannot be empty"):
        firewall.compile_partition_key(empty_ctx)


def test_firewall_record_access_and_filter_wrapping() -> None:
    """Test access authorization and automatic filter wrapping."""
    firewall = MemoryNamespaceFirewall()
    ctx_a = TenantMemoryContext(user_id="user_a", agent_id="agent_1")
    ctx_b = TenantMemoryContext(user_id="user_b", agent_id="agent_1")

    spec_a = firewall.compile_partition_key(ctx_a)
    spec_b = firewall.compile_partition_key(ctx_b)

    # Context A can access its own record
    assert firewall.validate_record_access(spec_a.composite_key, ctx_a) is True
    # Context A cannot access Context B's record
    assert firewall.validate_record_access(spec_b.composite_key, ctx_a) is False

    # Filter wrapping
    raw_filter = {"category": "project_notes"}
    wrapped = firewall.wrap_filter_criteria(ctx_a, raw_filter)
    assert wrapped["_partition_key"] == spec_a.composite_key
    assert wrapped["_user_id"] == "user_a"
    assert wrapped["_agent_id"] == "agent_1"
    assert wrapped["category"] == "project_notes"


def test_cross_tenant_probe_runner_zero_leakage() -> None:
    """Test that synthetic adversarial invariant probes confirm 100% isolation."""
    runner = CrossTenantProbeRunner(environment_type="cloud_dedicated_sandbox")
    current_context = TenantMemoryContext(
        user_id="corp_tenant_alpha",
        agent_id="finance_bot",
        scope="agent",
    )

    report = runner.run_sybil_isolation_audit(current_context)

    assert report.is_safe is True
    assert report.total_probes_run >= 4
    assert report.cross_hits_count == 0
    assert report.isolation_pass_rate == 100.0
    assert report.environment_type == "cloud_dedicated_sandbox"
    assert report.partition_integrity_verified is True
    assert "Zero cross-contamination confirmed" in report.summary

    # Ensure all scenarios passed
    for scenario in report.scenario_results:
        assert scenario.is_isolated is True
        assert scenario.cross_hits == 0
