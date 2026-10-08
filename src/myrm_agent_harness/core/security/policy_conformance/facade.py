"""
[POS] src/myrm_agent_harness/core/security/policy_conformance/facade.py
[INPUT] uuid, types, drift_auditor, routing_verifier
[OUTPUT] AgentPolicyConformanceFacade
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import uuid

from .drift_auditor import DeclarativePolicyDriftAuditor
from .routing_verifier import SyntheticMessageRoutingVerifier
from .types import (
    AgentRuntimeConfig,
    ConfigDriftFinding,
    PolicyAuditorMetrics,
    PolicyBaseline,
    PolicyConformanceReport,
    RoutingRule,
    RoutingTestCase,
    RoutingVerificationResult,
)


class AgentPolicyConformanceFacade:
    """Unified entrypoint for policy conformance auditing and synthetic message routing verification."""

    def __init__(
        self,
        auditor: DeclarativePolicyDriftAuditor | None = None,
        routing_verifier: SyntheticMessageRoutingVerifier | None = None,
    ) -> None:
        self._auditor = auditor or DeclarativePolicyDriftAuditor()
        self._verifier = routing_verifier or SyntheticMessageRoutingVerifier()
        self._metrics = PolicyAuditorMetrics()

    @property
    def metrics(self) -> PolicyAuditorMetrics:
        """Shared operational telemetry counters."""
        return self._metrics

    def update_baseline(self, baseline: PolicyBaseline) -> None:
        """Update declarative enterprise baseline."""
        self._auditor.update_baseline(baseline)

    def get_baseline(self) -> PolicyBaseline:
        """Fetch active policy baseline."""
        return self._auditor.baseline

    def register_routing_rule(self, rule: RoutingRule) -> None:
        """Register semantic message routing rule for an agent."""
        self._verifier.register_rule(rule)

    def audit_agents(
        self, agents: tuple[AgentRuntimeConfig, ...]
    ) -> tuple[ConfigDriftFinding, ...]:
        """Perform drift audit on a collection of agent runtime configurations."""
        all_findings: list[ConfigDriftFinding] = []
        for agent in agents:
            findings = self._auditor.audit_agent(agent)
            all_findings.extend(findings)
        return tuple(all_findings)

    def remediate_agent(self, config: AgentRuntimeConfig) -> AgentRuntimeConfig:
        """Generate baseline-aligned configuration snapshot."""
        return self._auditor.remediate_to_baseline(config)

    def verify_routing(
        self, test_cases: tuple[RoutingTestCase, ...]
    ) -> tuple[RoutingVerificationResult, ...]:
        """Run synthetic conversation test cases to verify routing accuracy."""
        return self._verifier.verify_suite(test_cases)

    def run_full_conformance_audit(
        self,
        agents: tuple[AgentRuntimeConfig, ...],
        test_cases: tuple[RoutingTestCase, ...],
    ) -> PolicyConformanceReport:
        """Execute comprehensive audit: configuration drift evaluation and routing assertion."""
        self._metrics.audits_executed_total += 1
        self._metrics.agents_audited_total += len(agents)

        findings = self.audit_agents(agents)
        self._metrics.drifts_detected_total += len(findings)

        routing_results = self.verify_routing(test_cases)
        self._metrics.routing_checks_run_total += len(test_cases)
        passed_routes = sum(1 for r in routing_results if r.is_matched)
        self._metrics.routing_checks_passed_total += passed_routes

        score = self._auditor.calculate_score(findings)
        pass_rate = self._verifier.calculate_pass_rate(routing_results)

        badge = (
            f"🛡️ 策略合规评分: {score}/100 | "
            f"检测到 {len(findings)} 处漂移 | "
            f"路由断言通过率: {pass_rate:.1f}%"
        )

        return PolicyConformanceReport(
            audit_id=f"audit-{uuid.uuid4().hex[:12]}",
            conformance_score=score,
            total_agents_checked=len(agents),
            drift_findings=findings,
            routing_pass_rate=pass_rate,
            routing_results=routing_results,
            summary_badge=badge,
        )
