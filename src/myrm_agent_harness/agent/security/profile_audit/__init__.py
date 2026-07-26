"""Agent Profile configuration exposure aggregation audit engine.

[INPUT]
- ProfileAuditInput DTO (POS: assembled by caller from Agent Profile data)

[OUTPUT]
- ProfileAuditResult: aggregate risk score, risk level, and per-checker findings

[POS]
Deterministic rule-based static analysis engine. Receives a ProfileAuditInput DTO
containing the Agent's enabled tools, MCP configs, skill scan summaries, subagent
bindings, cron jobs, and security policy — produces a unified risk assessment.
Zero LLM calls, zero I/O. Pure computation.
"""

from myrm_agent_harness.agent.security.profile_audit.engine import run_profile_audit
from myrm_agent_harness.agent.security.profile_audit.types import (
    AuditFinding,
    AuditSeverity,
    ProfileAuditInput,
    ProfileAuditResult,
    RiskLevel,
)

__all__ = [
    "AuditFinding",
    "AuditSeverity",
    "ProfileAuditInput",
    "ProfileAuditResult",
    "RiskLevel",
    "run_profile_audit",
]
