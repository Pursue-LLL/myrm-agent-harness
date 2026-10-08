"""Unit tests for Kernel Continuous Enforcement, Formal Policy Prover,
Revocation Residue, and Supply Chain Suite.

Verifies 3D runtime enforcement, protocol upgrade header defenses,
formal prover symbolic verification, policy hot-reloading, and post-revocation audits.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.kernel_continuous_enforcement import (
    EnforcementDecision,
    FormalPolicyProver,
    KernelContinuousEnforcementFacade,
    NetworkPolicyRule,
    PolicyChangeProposal,
    ProtocolKind,
    RevocationResidueVerifier,
    RuntimeHopCheckRequest,
    ThreeDimContinuousEnforcer,
)


def test_three_dim_enforcer_binaries_and_endpoints() -> None:
    rule = NetworkPolicyRule(
        rule_id="rule-curl-github",
        allowed_binaries=("curl", "git"),
        endpoint_host="api.github.com",
        endpoint_port=443,
        path_glob="/repos/*",
        protocol=ProtocolKind.REST,
    )
    enforcer = ThreeDimContinuousEnforcer((rule,))

    # 1. Allowed binary and path
    req_allowed = RuntimeHopCheckRequest(
        binary_name="curl",
        host="api.github.com",
        port=443,
        path="/repos/octocat/hello-world",
        protocol=ProtocolKind.REST,
    )
    res_allowed = enforcer.evaluate(req_allowed)
    assert res_allowed.decision == EnforcementDecision.ALLOW
    assert res_allowed.rule_id == "rule-curl-github"

    # 2. Unauthorized binary (e.g., untrusted python shell)
    req_bad_bin = RuntimeHopCheckRequest(
        binary_name="python3",
        host="api.github.com",
        port=443,
        path="/repos/octocat/hello-world",
        protocol=ProtocolKind.REST,
    )
    res_bad_bin = enforcer.evaluate(req_bad_bin)
    assert res_bad_bin.decision == EnforcementDecision.DENY
    assert "not permitted" in res_bad_bin.reason

    # 3. Unregistered endpoint
    req_unregistered = RuntimeHopCheckRequest(
        binary_name="curl",
        host="attacker.com",
        port=443,
        path="/exfil",
        protocol=ProtocolKind.REST,
    )
    res_unregistered = enforcer.evaluate(req_unregistered)
    assert res_unregistered.decision == EnforcementDecision.DENY
    assert "No matching policy rule" in res_unregistered.reason


def test_three_dim_enforcer_path_glob_specificity() -> None:
    broad_rule = NetworkPolicyRule(
        rule_id="rule-broad",
        allowed_binaries=("node",),
        endpoint_host="service.local",
        endpoint_port=8080,
        path_glob="/api/*",
        protocol=ProtocolKind.REST,
    )
    specific_rule = NetworkPolicyRule(
        rule_id="rule-specific",
        allowed_binaries=("node",),
        endpoint_host="service.local",
        endpoint_port=8080,
        path_glob="/api/v2/secure/*",
        protocol=ProtocolKind.REST,
    )
    enforcer = ThreeDimContinuousEnforcer((broad_rule, specific_rule))

    req = RuntimeHopCheckRequest(
        binary_name="node",
        host="service.local",
        port=8080,
        path="/api/v2/secure/resource",
        protocol=ProtocolKind.REST,
    )
    res = enforcer.evaluate(req)
    assert res.decision == EnforcementDecision.ALLOW
    # Longest path glob wins
    assert res.rule_id == "rule-specific"


def test_three_dim_enforcer_protocol_and_upgrade_smuggling() -> None:
    mcp_rule = NetworkPolicyRule(
        rule_id="rule-mcp-internal",
        allowed_binaries=("myrm-worker",),
        endpoint_host="mcp.internal",
        endpoint_port=9000,
        path_glob="/mcp/*",
        protocol=ProtocolKind.MCP,
        allow_upgrade_header=False,
    )
    enforcer = ThreeDimContinuousEnforcer((mcp_rule,))

    # Regular MCP request without Upgrade header
    req_normal = RuntimeHopCheckRequest(
        binary_name="myrm-worker",
        host="mcp.internal",
        port=9000,
        path="/mcp/tools",
        protocol=ProtocolKind.MCP,
        has_upgrade_header=False,
    )
    res_normal = enforcer.evaluate(req_normal)
    assert res_normal.decision == EnforcementDecision.ALLOW

    # Malicious attempt to smuggle Upgrade header on MCP endpoint
    req_smuggle = RuntimeHopCheckRequest(
        binary_name="myrm-worker",
        host="mcp.internal",
        port=9000,
        path="/mcp/tools",
        protocol=ProtocolKind.MCP,
        has_upgrade_header=True,
    )
    res_smuggle = enforcer.evaluate(req_smuggle)
    assert res_smuggle.decision == EnforcementDecision.DENY
    assert res_smuggle.violates_protocol_upgrade is True
    assert "Protocol upgrade header forbidden" in res_smuggle.reason


def test_formal_policy_prover_risk_flagging() -> None:
    prover = FormalPolicyProver()

    risky_rule = NetworkPolicyRule(
        rule_id="risky-admin-access",
        allowed_binaries=("*",),  # Wildcard binary
        endpoint_host="bastion.corp",
        endpoint_port=22,         # Sensitive SSH port
        path_glob="*",
        protocol=ProtocolKind.TCP,
    )
    proposal = PolicyChangeProposal(
        proposal_id="prop-001",
        agent_id="agent-claude",
        proposed_rules=(risky_rule,),
        justification="Need root ssh access to server",
        timestamp_iso="2026-10-07T12:00:00Z",
    )

    verdict = prover.prove_proposal(proposal)
    assert verdict.is_safe is False
    assert verdict.requires_human_approval is True
    assert verdict.risk_score >= 0.5
    assert len(verdict.flagged_risks) >= 2


def test_formal_policy_prover_clean_narrow_rule() -> None:
    prover = FormalPolicyProver()

    narrow_rule = NetworkPolicyRule(
        rule_id="narrow-gh-read",
        allowed_binaries=("git",),
        endpoint_host="github.com",
        endpoint_port=443,
        path_glob="/org/repo/info/refs",
        protocol=ProtocolKind.REST,
        provider_binding="github_oauth_app",
    )
    proposal = PolicyChangeProposal(
        proposal_id="prop-002",
        agent_id="agent-code",
        proposed_rules=(narrow_rule,),
        justification="Clone public repository",
        timestamp_iso="2026-10-07T12:00:00Z",
    )

    verdict = prover.prove_proposal(proposal)
    assert verdict.is_safe is True
    assert verdict.requires_human_approval is False
    assert verdict.risk_score == 0.0


def test_policy_hot_loading_workflow() -> None:
    facade = KernelContinuousEnforcementFacade()

    req = RuntimeHopCheckRequest(
        binary_name="worker-bin",
        host="external-api.com",
        port=443,
        path="/v1/data",
        protocol=ProtocolKind.REST,
    )

    # 1. Initially denied
    assert facade.evaluate_egress(req).decision == EnforcementDecision.DENY

    # 2. Agent submits proposal
    rule = NetworkPolicyRule(
        rule_id="rule-external-api",
        allowed_binaries=("worker-bin",),
        endpoint_host="external-api.com",
        endpoint_port=443,
        path_glob="/v1/*",
        protocol=ProtocolKind.REST,
    )
    proposal = PolicyChangeProposal(
        proposal_id="prop-hotload",
        agent_id="agent-worker",
        proposed_rules=(rule,),
        justification="Access data API",
        timestamp_iso="2026-10-07T12:00:00Z",
    )
    facade.submit_proposal(proposal)

    # 3. Approve proposal -> rules hot-loaded
    assert facade.approve_proposal("prop-hotload") is True

    # 4. Retry request -> now allowed
    res_retry = facade.evaluate_egress(req)
    assert res_retry.decision == EnforcementDecision.ALLOW
    assert res_retry.rule_id == "rule-external-api"


def test_revocation_residue_verifier() -> None:
    verifier = RevocationResidueVerifier()

    # Dirty post-run state with lingering child process and token
    dirty_report = verifier.audit_run_residue(
        run_id="run-dirty-1",
        active_pids=(4512,),
        open_sockets=("127.0.0.1:9090",),
        temp_files=("/tmp/.agent_token_cached",),
        cached_tokens=("ghp_lingering_secret_token",),
    )
    assert dirty_report.is_fully_clean is False
    assert len(dirty_report.lingering_pids) == 1
    assert len(dirty_report.lingering_sockets) == 1

    # Completely clean post-run state
    clean_report = verifier.audit_run_residue(run_id="run-clean-2")
    assert clean_report.is_fully_clean is True
    assert len(clean_report.lingering_pids) == 0
