"""Profile audit data transfer objects.

[INPUT]
- (none)

[OUTPUT]
- AuditSeverity: finding severity enum
- RiskLevel: qualitative risk classification
- AuditFinding: single audit finding with source location
- ProfileAuditInput: complete input DTO for the audit engine
- ProfileAuditResult: complete output DTO with score, level, and findings

[POS]
Pure DTO definitions. No logic, no I/O. Consumed by engine.py and all checkers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum


class AuditSeverity(IntEnum):
    """Finding severity — determines deduction weight."""

    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class RiskLevel(StrEnum):
    """Qualitative risk classification for the overall profile."""

    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class AuditFinding:
    """A single audit finding with actionable context."""

    checker: str
    severity: AuditSeverity
    title: str
    description: str
    recommendation: str
    source_location: str = ""


@dataclass(frozen=True, slots=True)
class SkillScanInput:
    """Skill scan summary for audit aggregation."""

    skill_id: str
    skill_name: str
    score: int
    trust_recommendation: str
    finding_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MCPConfigInput:
    """MCP server configuration snapshot for audit."""

    server_name: str
    transport_type: str
    has_auth: bool = False
    finding_count: int = 0
    max_severity: str = ""


@dataclass(frozen=True, slots=True)
class SubagentInput:
    """Sub-agent binding info for recursive risk assessment."""

    agent_id: str
    agent_name: str
    has_own_tools: bool = False
    has_own_mcps: bool = False
    has_own_subagents: bool = False


@dataclass(frozen=True, slots=True)
class CronJobInput:
    """Cron job binding for unattended risk evaluation."""

    job_id: str
    schedule: str
    agent_id: str
    has_dangerous_tools: bool = False


@dataclass(frozen=True, slots=True)
class SecurityPolicyInput:
    """Current security policy state for gap detection."""

    has_path_policy: bool = False
    has_network_policy: bool = False
    has_capability_restrictions: bool = False
    approval_timeout_seconds: int | None = None
    domain_hitl_enabled: bool = False


@dataclass(frozen=True, slots=True)
class ProfileAuditInput:
    """Complete input DTO for the profile audit engine."""

    agent_id: str
    agent_name: str
    enabled_builtin_tools: tuple[str, ...] = ()
    mcp_configs: tuple[MCPConfigInput, ...] = ()
    skill_scans: tuple[SkillScanInput, ...] = ()
    subagents: tuple[SubagentInput, ...] = ()
    cron_jobs: tuple[CronJobInput, ...] = ()
    security_policy: SecurityPolicyInput = field(default_factory=SecurityPolicyInput)


@dataclass(frozen=True, slots=True)
class ProfileAuditResult:
    """Complete audit result with score, risk level, and findings."""

    score: int
    risk_level: RiskLevel
    findings: tuple[AuditFinding, ...] = ()
    total_findings: int = 0
    finding_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "risk_level": self.risk_level.value,
            "findings": [
                {
                    "checker": f.checker,
                    "severity": f.severity.name.lower(),
                    "title": f.title,
                    "description": f.description,
                    "recommendation": f.recommendation,
                    "source_location": f.source_location,
                }
                for f in self.findings
            ],
            "total_findings": self.total_findings,
            "finding_counts": self.finding_counts,
        }
