"""
[POS] src/myrm_agent_harness/core/security/policy_conformance/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] DriftSeverity, PolicyBaseline, AgentRuntimeConfig, ConfigDriftFinding, RoutingRule, RoutingTestCase, RoutingVerificationResult, PolicyConformanceReport, PolicyAuditorMetrics
Domain types for Agent Policy Conformance Auditor & Message Routing Verification Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DriftSeverity(StrEnum):
    """Classification of configuration drift against declarative baseline."""

    COMPLIANT = "COMPLIANT"
    WARNING_DRIFT = "WARNING_DRIFT"
    CRITICAL_VIOLATION = "CRITICAL_VIOLATION"


@dataclass(frozen=True)
class PolicyBaseline:
    """Enterprise policy baseline declaring permitted models, tools, and security gates."""

    baseline_id: str
    allowed_model_providers: tuple[str, ...] = ("openai", "anthropic", "deepseek")
    allowed_mcp_servers: tuple[str, ...] = ("memory", "calculator", "browser")
    prohibited_domains: tuple[str, ...] = ("*.onion", "darknet.internal", "phishing-test.org")
    max_temperature: float = 1.0
    enforce_approval_gate: bool = True


@dataclass(frozen=True)
class AgentRuntimeConfig:
    """Observed runtime configuration snapshot of an active agent."""

    agent_id: str
    model_provider: str
    loaded_mcp_servers: tuple[str, ...] = ()
    configured_egress_domains: tuple[str, ...] = ()
    temperature: float = 0.7
    approval_gate_enabled: bool = True


@dataclass(frozen=True)
class ConfigDriftFinding:
    """Individual non-conformance finding identified during baseline audit."""

    agent_id: str
    field_name: str
    severity: DriftSeverity
    expected_value: str
    actual_value: str
    remediation_advice: str


@dataclass(frozen=True)
class RoutingRule:
    """Semantic mapping rule routing conversations to specialized agents."""

    agent_id: str
    keywords: tuple[str, ...] = ()
    intent_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutingTestCase:
    """Synthetic conversation query used for zero-cost message-routing assertion."""

    case_id: str
    sample_message: str
    expected_agent_id: str
    required_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutingVerificationResult:
    """Outcome of testing a synthetic incoming query against routing rules."""

    case_id: str
    is_matched: bool
    expected_agent_id: str
    routed_agent_id: str
    confidence_score: float
    diagnostic: str


@dataclass(frozen=True)
class PolicyConformanceReport:
    """Comprehensive policy conformance and message-routing health report."""

    audit_id: str
    conformance_score: int
    total_agents_checked: int
    drift_findings: tuple[ConfigDriftFinding, ...]
    routing_pass_rate: float
    routing_results: tuple[RoutingVerificationResult, ...]
    summary_badge: str


@dataclass
class PolicyAuditorMetrics:
    """Telemetry counters for policy audits and routing verification runs."""

    audits_executed_total: int = 0
    agents_audited_total: int = 0
    drifts_detected_total: int = 0
    routing_checks_run_total: int = 0
    routing_checks_passed_total: int = 0
