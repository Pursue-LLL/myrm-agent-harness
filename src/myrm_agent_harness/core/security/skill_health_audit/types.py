"""
[POS] src/myrm_agent_harness/core/security/skill_health_audit/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] SkillSecurityMetadata, TaintFlowFinding, FourRowHealthCard, SkillHealthAuditVerdict, IntelLookupStatus
Domain types for Conversational Skill Health Audit & Stealth Exfiltration Taint Sentinel Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class IntelLookupStatus(StrEnum):
    """Status of privacy-minimized cloud threat intelligence lookup."""

    VERIFIED_BENIGN = "verified_benign"
    KNOWN_MALICIOUS = "known_malicious"
    UNAVAILABLE_OFFLINE = "unavailable_offline"
    LOOKUP_ERROR = "lookup_error"


class TaintSeverity(StrEnum):
    """Severity tier for identified taint and undeclared exfiltration flows."""

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL_BLOCK = "critical_block"


@dataclass(frozen=True)
class ExternalRequestDeclaration:
    """Declared outbound network endpoint in skill frontmatter."""

    url: str
    purpose: str
    data_sent: tuple[str, ...] = ()
    failure_mode: str = "graceful_degradation"


@dataclass(frozen=True)
class SkillSecurityMetadata:
    """Declarative security metadata parsed from skill frontmatter/manifest."""

    skill_name: str
    publisher: str = "unknown"
    official_repo: str | None = None
    external_requests: tuple[ExternalRequestDeclaration, ...] = ()
    env_vars: tuple[str, ...] = ()
    live_probe_command: str | None = None
    binary_caution: str | None = None


@dataclass(frozen=True)
class TaintFlowFinding:
    """AST taint finding linking sensitive source to network sink."""

    source_type: str
    sink_type: str
    line_number: int
    symbol: str
    is_declared: bool
    severity: TaintSeverity
    description: str


@dataclass(frozen=True)
class FourRowHealthCard:
    """Plain-language 4-row security posture summary card without technical jargon."""

    source_credibility: str
    file_boundary: str
    network_egress: str
    dangerous_syscalls: str


@dataclass(frozen=True)
class SkillHealthAuditVerdict:
    """Comprehensive verdict returned by the in-chat skill health auditor."""

    skill_name: str
    content_sha256: str
    health_score: int
    is_clean: bool
    requires_attention: bool
    intel_status: IntelLookupStatus
    plain_language_card: FourRowHealthCard
    taint_findings: tuple[TaintFlowFinding, ...]
    declared_requests_count: int
    undeclared_sinks_count: int
    actionable_advice: str
    disclaimer: str = (
        "This score evaluates declared vs static AST AST patterns and CVE hash intelligence. "
        "It does not guarantee absence of novel or unmodeled runtime zero-day vulnerabilities."
    )
    raw_sarif: dict[str, str | int | list[dict[str, str | int]]] = field(default_factory=dict)
