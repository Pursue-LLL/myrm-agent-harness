"""Domain types and contracts for Orchestrator Scope Guardrails & Safe Team Design Mode (Item 37).

[INPUT]
- Team design candidates, per-role tool requests, and safe guardrail configurations.

[OUTPUT]
- Strongly-typed domain models for violation findings, safe team design configs,
  and audit evaluation results.

[POS]
- Harness coordination layer contracts for orchestrator permission bounds and fan-out caps.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class ViolationType(enum.StrEnum):
    """Categorized safety guardrail violation types."""

    FORBIDDEN_TOOL = "forbidden_tool"
    ROLE_SCOPE_EXCEEDED = "role_scope_exceeded"
    FANOUT_LIMIT_EXCEEDED = "fanout_limit_exceeded"
    HIGH_RISK_REQUIRE_HITL = "high_risk_require_hitl"


class ViolationSeverity(enum.StrEnum):
    """Severity classification for guardrail violations."""

    BLOCKER = "blocker"
    WARNING = "warning"


@dataclass(frozen=True)
class ScopeViolationFinding:
    """An individual scope violation or privilege escalation detected during team design."""

    role_key: str
    tool_name: str
    violation_type: ViolationType
    severity: ViolationSeverity
    recommendation: str


@dataclass(frozen=True)
class SafeTeamDesignConfig:
    """Configuration governing safe team design mode constraints and minimum necessary privileges."""

    max_fanout_cap: int = 5
    require_hitl_for_high_risk: bool = True
    forbidden_tools: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "system_exec",
                "eval_exec",
                "db_drop",
                "credential_export",
                "raw_bash_root",
            }
        )
    )
    role_tool_allowlists: dict[str, frozenset[str]] = field(
        default_factory=lambda: {
            "orchestrator": frozenset(
                {"spawn_subagent", "delegate_task", "steer_subagent", "roster_read"}
            ),
            "researcher": frozenset(
                {"web_search", "web_fetch", "file_read", "search_directory"}
            ),
            "coder": frozenset(
                {"file_read", "file_write", "linter_run", "test_runner", "diff_view"}
            ),
            "reviewer": frozenset(
                {"file_read", "diff_view", "linter_run", "audit_report"}
            ),
            "specialist": frozenset(
                {"file_read", "diff_view", "specialist_eval", "web_search"}
            ),
        }
    )


@dataclass(frozen=True)
class MemberScopeCandidate:
    """A single teammate's proposed role and requested tools within a squad design."""

    role_key: str
    display_name: str
    requested_tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TeamGuardrailsEvaluationResult:
    """Consolidated outcome of evaluating a proposed team design against safe guardrails."""

    is_safe: bool
    sanitized_tools_map: dict[str, list[str]]
    violations: list[ScopeViolationFinding]
    fanout_capped: bool
    original_member_count: int
    approved_member_count: int
    audit_summary: str
