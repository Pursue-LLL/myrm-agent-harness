"""
[POS] tests/unit/test_agent_policy_conformance_suite.py
Unit tests for Agent Policy Conformance Auditor & Message Routing Verification Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.policy_conformance import (
    AgentPolicyConformanceFacade,
    AgentRuntimeConfig,
    DeclarativePolicyDriftAuditor,
    DriftSeverity,
    PolicyBaseline,
    RoutingRule,
    RoutingTestCase,
    SyntheticMessageRoutingVerifier,
)


@pytest.fixture
def standard_baseline() -> PolicyBaseline:
    return PolicyBaseline(
        baseline_id="baseline-standard-v1",
        allowed_model_providers=("openai", "anthropic", "deepseek"),
        allowed_mcp_servers=("memory", "calculator", "browser"),
        prohibited_domains=("*.onion", "darknet.internal", "malware.site"),
        max_temperature=0.8,
        enforce_approval_gate=True,
    )


@pytest.fixture
def compliant_agent() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id="agent-search-01",
        model_provider="anthropic",
        loaded_mcp_servers=("memory", "browser"),
        configured_egress_domains=("api.safe-service.com",),
        temperature=0.5,
        approval_gate_enabled=True,
    )


@pytest.fixture
def non_compliant_agent() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id="agent-rogue-02",
        model_provider="unapproved_shadow_llm",
        loaded_mcp_servers=("memory", "arbitrary_backdoor_tool"),
        configured_egress_domains=("c2.darknet.internal", "hacker.onion"),
        temperature=1.2,
        approval_gate_enabled=False,
    )


def test_declarative_drift_auditor_compliant(
    standard_baseline: PolicyBaseline, compliant_agent: AgentRuntimeConfig
) -> None:
    auditor = DeclarativePolicyDriftAuditor(baseline=standard_baseline)
    findings = auditor.audit_agent(compliant_agent)
    assert len(findings) == 0

    score = auditor.calculate_score(findings)
    assert score == 100


def test_declarative_drift_auditor_violations_and_remediation(
    standard_baseline: PolicyBaseline, non_compliant_agent: AgentRuntimeConfig
) -> None:
    auditor = DeclarativePolicyDriftAuditor(baseline=standard_baseline)
    findings = auditor.audit_agent(non_compliant_agent)

    # Expected 5 violations: model_provider, loaded_mcp_servers, 2 prohibited egress domains, temperature, approval_gate
    assert len(findings) == 6  # 2 prohibited domains -> 6 total findings

    crit_findings = [f for f in findings if f.severity == DriftSeverity.CRITICAL_VIOLATION]
    warn_findings = [f for f in findings if f.severity == DriftSeverity.WARNING_DRIFT]

    assert len(crit_findings) >= 4  # provider, 2 egress, approval_gate
    assert len(warn_findings) >= 2  # mcp, temperature

    score = auditor.calculate_score(findings)
    assert score == 10  # Multiple critical penalties (4*20 + 2*5 = 90 -> 100-90=10)

    # Test remediation
    remediated = auditor.remediate_to_baseline(non_compliant_agent)
    assert remediated.model_provider == standard_baseline.allowed_model_providers[0]
    assert "arbitrary_backdoor_tool" not in remediated.loaded_mcp_servers
    assert "memory" in remediated.loaded_mcp_servers
    assert len(remediated.configured_egress_domains) == 0
    assert remediated.temperature == standard_baseline.max_temperature
    assert remediated.approval_gate_enabled is True

    # Re-audit remediated config
    remediated_findings = auditor.audit_agent(remediated)
    assert len(remediated_findings) == 0
    assert auditor.calculate_score(remediated_findings) == 100


def test_synthetic_message_routing_verifier() -> None:
    rules = (
        RoutingRule(
            agent_id="code_assistant",
            keywords=("code", "python", "debug", "refactor"),
            intent_tags=("programming", "development"),
        ),
        RoutingRule(
            agent_id="finance_analyst",
            keywords=("stock", "dividend", "revenue", "financial"),
            intent_tags=("accounting", "finance"),
        ),
    )
    verifier = SyntheticMessageRoutingVerifier(rules=rules)

    test_cases = (
        RoutingTestCase(
            case_id="case-1",
            sample_message="Please help me debug this Python code snippet",
            expected_agent_id="code_assistant",
            required_keywords=("debug",),
        ),
        RoutingTestCase(
            case_id="case-2",
            sample_message="Calculate the dividend revenue and financial report",
            expected_agent_id="finance_analyst",
            required_keywords=("dividend",),
        ),
        RoutingTestCase(
            case_id="case-3-missing-kw",
            sample_message="Tell me a joke about dogs",
            expected_agent_id="code_assistant",
            required_keywords=("python",),
        ),
    )

    results = verifier.verify_suite(test_cases)
    assert len(results) == 3
    assert results[0].is_matched is True
    assert results[0].routed_agent_id == "code_assistant"
    assert results[0].confidence_score > 0.5

    assert results[1].is_matched is True
    assert results[1].routed_agent_id == "finance_analyst"

    assert results[2].is_matched is False
    assert "missing" in results[2].diagnostic

    pass_rate = verifier.calculate_pass_rate(results)
    assert pytest.approx(pass_rate, rel=1e-2) == 66.67


def test_agent_policy_conformance_facade_end_to_end(
    standard_baseline: PolicyBaseline,
    compliant_agent: AgentRuntimeConfig,
    non_compliant_agent: AgentRuntimeConfig,
) -> None:
    facade = AgentPolicyConformanceFacade()
    facade.update_baseline(standard_baseline)
    assert facade.get_baseline().baseline_id == "baseline-standard-v1"

    facade.register_routing_rule(
        RoutingRule(
            agent_id="agent-search-01",
            keywords=("search", "query", "web"),
            intent_tags=("information_retrieval",),
        )
    )

    test_cases = (
        RoutingTestCase(
            case_id="rt-01",
            sample_message="Please search web information for AI updates",
            expected_agent_id="agent-search-01",
            required_keywords=("search",),
        ),
    )

    agents = (compliant_agent, non_compliant_agent)
    report = facade.run_full_conformance_audit(agents=agents, test_cases=test_cases)

    assert report.total_agents_checked == 2
    assert len(report.drift_findings) == 6
    assert report.routing_pass_rate == 100.0
    assert "🛡️ 策略合规评分" in report.summary_badge
    assert facade.metrics.audits_executed_total == 1
    assert facade.metrics.agents_audited_total == 2
    assert facade.metrics.drifts_detected_total == 6
    assert facade.metrics.routing_checks_run_total == 1
    assert facade.metrics.routing_checks_passed_total == 1
