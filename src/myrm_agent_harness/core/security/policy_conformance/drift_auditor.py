"""
[POS] src/myrm_agent_harness/core/security/policy_conformance/drift_auditor.py
[INPUT] types
[OUTPUT] DeclarativePolicyDriftAuditor
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .types import (
    AgentRuntimeConfig,
    ConfigDriftFinding,
    DriftSeverity,
    PolicyBaseline,
)

logger = logging.getLogger(__name__)


class DeclarativePolicyDriftAuditor:
    """Audits agent runtime configurations against declarative enterprise policy baselines."""

    def __init__(self, baseline: PolicyBaseline | None = None) -> None:
        self._baseline = baseline or PolicyBaseline(baseline_id="default-baseline-2026")

    @property
    def baseline(self) -> PolicyBaseline:
        return self._baseline

    def update_baseline(self, new_baseline: PolicyBaseline) -> None:
        """Update declarative baseline contract."""
        self._baseline = new_baseline
        logger.info("Updated policy baseline: %s", new_baseline.baseline_id)

    def audit_agent(
        self, config: AgentRuntimeConfig
    ) -> tuple[ConfigDriftFinding, ...]:
        """Audit single agent runtime config against baseline, returning detected drift findings."""
        findings: list[ConfigDriftFinding] = []

        # 1. Model Provider Assertion
        prov_clean = config.model_provider.strip().lower()
        allowed_provs = {p.strip().lower() for p in self._baseline.allowed_model_providers}
        if prov_clean not in allowed_provs:
            findings.append(
                ConfigDriftFinding(
                    agent_id=config.agent_id,
                    field_name="model_provider",
                    severity=DriftSeverity.CRITICAL_VIOLATION,
                    expected_value=f"One of {sorted(allowed_provs)}",
                    actual_value=config.model_provider,
                    remediation_advice=(
                        f"Reconfigure agent '{config.agent_id}' to use an approved provider "
                        f"such as '{self._baseline.allowed_model_providers[0]}'"
                    ),
                )
            )

        # 2. MCP Server Authorizations
        allowed_mcp = {m.strip().lower() for m in self._baseline.allowed_mcp_servers}
        for mcp in config.loaded_mcp_servers:
            if mcp.strip().lower() not in allowed_mcp:
                findings.append(
                    ConfigDriftFinding(
                        agent_id=config.agent_id,
                        field_name="loaded_mcp_servers",
                        severity=DriftSeverity.WARNING_DRIFT,
                        expected_value=f"Subsets of {sorted(allowed_mcp)}",
                        actual_value=mcp,
                        remediation_advice=f"Unload untrusted or unapproved MCP server '{mcp}'",
                    )
                )

        # 3. Prohibited Egress Domains
        for domain in config.configured_egress_domains:
            if self._is_prohibited_domain(domain):
                findings.append(
                    ConfigDriftFinding(
                        agent_id=config.agent_id,
                        field_name="configured_egress_domains",
                        severity=DriftSeverity.CRITICAL_VIOLATION,
                        expected_value="Clean domain list without prohibited destinations",
                        actual_value=domain,
                        remediation_advice=f"Remove prohibited egress destination '{domain}'",
                    )
                )

        # 4. Temperature Guardrail
        if config.temperature > self._baseline.max_temperature:
            findings.append(
                ConfigDriftFinding(
                    agent_id=config.agent_id,
                    field_name="temperature",
                    severity=DriftSeverity.WARNING_DRIFT,
                    expected_value=f"<= {self._baseline.max_temperature:.2f}",
                    actual_value=f"{config.temperature:.2f}",
                    remediation_advice=(
                        f"Lower model sampling temperature to at most {self._baseline.max_temperature:.2f}"
                    ),
                )
            )

        # 5. Approval Gate Enforcement
        if self._baseline.enforce_approval_gate and not config.approval_gate_enabled:
            findings.append(
                ConfigDriftFinding(
                    agent_id=config.agent_id,
                    field_name="approval_gate_enabled",
                    severity=DriftSeverity.CRITICAL_VIOLATION,
                    expected_value="True (enforce_approval_gate is mandated)",
                    actual_value="False",
                    remediation_advice=f"Enable execution approval gate on agent '{config.agent_id}'",
                )
            )

        return tuple(findings)

    def calculate_score(self, findings: tuple[ConfigDriftFinding, ...]) -> int:
        """Calculate conformance health score from 100 downwards based on findings severity."""
        penalty = 0
        for f in findings:
            if f.severity == DriftSeverity.CRITICAL_VIOLATION:
                penalty += 20
            elif f.severity == DriftSeverity.WARNING_DRIFT:
                penalty += 5
        return max(0, 100 - penalty)

    def _is_prohibited_domain(self, domain: str) -> bool:
        """Check whether domain violates prohibited domain policies (wildcards and subdomains included)."""
        dom = domain.strip().lower()
        for p in self._baseline.prohibited_domains:
            p_clean = p.strip().lower()
            if p_clean.startswith("*."):
                suffix = p_clean[1:]  # e.g. .onion
                if dom.endswith(suffix):
                    return True
            elif dom == p_clean or dom.endswith(f".{p_clean}"):
                return True
        return False

    def remediate_to_baseline(self, config: AgentRuntimeConfig) -> AgentRuntimeConfig:
        """Produce aligned configuration snapshot conforming 100% to baseline rules."""
        safe_provider = (
            config.model_provider
            if config.model_provider.strip().lower()
            in {p.strip().lower() for p in self._baseline.allowed_model_providers}
            else self._baseline.allowed_model_providers[0]
        )
        safe_mcp = tuple(
            m
            for m in config.loaded_mcp_servers
            if m.strip().lower()
            in {allowed.strip().lower() for allowed in self._baseline.allowed_mcp_servers}
        )
        safe_egress = tuple(
            d
            for d in config.configured_egress_domains
            if not self._is_prohibited_domain(d)
        )
        safe_temp = min(config.temperature, self._baseline.max_temperature)
        safe_approval = True if self._baseline.enforce_approval_gate else config.approval_gate_enabled

        return AgentRuntimeConfig(
            agent_id=config.agent_id,
            model_provider=safe_provider,
            loaded_mcp_servers=safe_mcp,
            configured_egress_domains=safe_egress,
            temperature=safe_temp,
            approval_gate_enabled=safe_approval,
        )
