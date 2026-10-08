"""
Unit tests for Strict Target Scope Authorization & Egress Boundary Suite.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.target_scope_boundary import (
    ScopeVerdict,
    StrictTargetScopeBoundarySuite,
    TargetScopeContract,
    TargetScopeContractValidator,
)


def _build_sample_contract(is_active: bool = True) -> TargetScopeContract:
    return TargetScopeContract(
        contract_id="roe-contract-alpha",
        engagement_name="Q4 RedTeam Authorized Pentest",
        authorized_domains=("*.pentest.corp", "target.local"),
        authorized_cidrs=("10.10.0.0/16", "192.168.50.0/24"),
        prohibited_targets=("payment.pentest.corp", "10.10.99.1"),
        signed_by="ciso_office",
        signature_hash="sha256_mock_sig_12345",
        is_active=is_active,
    )


def test_scope_contract_validator_domain_and_ip() -> None:
    validator = TargetScopeContractValidator()
    contract = _build_sample_contract()

    # 1. Cloud metadata checks
    assert validator.is_cloud_metadata("169.254.169.254")
    assert validator.is_cloud_metadata("metadata.google.internal")
    assert not validator.is_cloud_metadata("api.pentest.corp")

    # 2. Domain in scope
    assert validator.is_domain_in_scope("app.pentest.corp", contract)
    assert validator.is_domain_in_scope("target.local", contract)
    assert not validator.is_domain_in_scope("unauthorized.com", contract)

    # 3. Explicit prohibited target in scope takes precedence
    assert not validator.is_domain_in_scope("payment.pentest.corp", contract)

    # 4. IP in scope
    assert validator.is_ip_in_scope("10.10.1.5", contract)
    assert validator.is_ip_in_scope("192.168.50.100", contract)
    assert not validator.is_ip_in_scope("172.16.0.1", contract)
    assert not validator.is_ip_in_scope("10.10.99.1", contract)  # Prohibited IP


def test_egress_boundary_interceptor_and_kill_switch() -> None:
    suite = StrictTargetScopeBoundarySuite()
    contract = _build_sample_contract()
    suite.set_active_contract(contract)

    # 1. In scope domain
    res_domain = suite.verify_target("web.pentest.corp")
    assert res_domain.is_allowed
    assert res_domain.verdict == ScopeVerdict.IN_SCOPE_ALLOWED

    # 2. In scope domain with matching resolved IP
    res_domain_ip = suite.verify_target("web.pentest.corp", resolved_ip="10.10.5.20")
    assert res_domain_ip.is_allowed
    assert res_domain_ip.verdict == ScopeVerdict.IN_SCOPE_ALLOWED

    # 3. Domain matches, but resolved IP is outside authorized CIDRs (e.g. CNAME drift)
    res_ip_violation = suite.verify_target("web.pentest.corp", resolved_ip="8.8.8.8")
    assert not res_ip_violation.is_allowed
    assert res_ip_violation.verdict == ScopeVerdict.UNAUTHORIZED_IP_BLOCKED

    # 4. Out of scope domain
    res_out = suite.verify_target("malicious.external.org")
    assert not res_out.is_allowed
    assert res_out.verdict == ScopeVerdict.OUT_OF_SCOPE_BLOCKED

    # 5. Cloud metadata prohibited
    res_meta = suite.verify_target("169.254.169.254")
    assert not res_meta.is_allowed
    assert res_meta.verdict == ScopeVerdict.CLOUD_METADATA_PROHIBITED

    # 6. Emergency Kill-Switch engagement
    suite.activate_kill_switch()
    assert suite.is_kill_switch_active()

    res_killed = suite.verify_target("web.pentest.corp")
    assert not res_killed.is_allowed
    assert res_killed.verdict == ScopeVerdict.EMERGENCY_KILL_SWITCH_ACTIVE

    # Reset kill-switch
    suite.reset_kill_switch()
    assert not suite.is_kill_switch_active()
    assert suite.verify_target("web.pentest.corp").is_allowed


def test_target_scope_boundary_facade_and_metrics() -> None:
    suite = StrictTargetScopeBoundarySuite()
    contract = _build_sample_contract()
    suite.set_active_contract(contract)

    # Allowed check
    suite.verify_target("web.pentest.corp")
    # Blocked check
    suite.verify_target("evil.com")
    # Metadata probe
    suite.verify_target("169.254.169.254")
    # Kill switch
    suite.activate_kill_switch()
    suite.verify_target("web.pentest.corp")
    suite.reset_kill_switch()

    metrics = suite.metrics
    assert metrics.scope_checks_total == 4
    assert metrics.in_scope_allowed_total == 1
    assert metrics.out_of_scope_blocked_total == 3
    assert metrics.metadata_probes_blocked_total == 1
    assert metrics.kill_switch_activations_total == 1
