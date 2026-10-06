"""Data types and schemas for dynamic working-set rules and architecture entropy draining.

Strictly typed, 0 Any. Defines path scoping, task phase routing,
rule telemetry, and entropy audit reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RuleTaskPhase(StrEnum):
    """Lifecycle phases of an agent task for rule scoping."""

    INTENT = "intent"
    SPEC = "spec"
    PLAN = "plan"
    CODE = "code"
    TEST = "test"
    REVIEW = "review"


# Alias for backward compatibility
TaskPhase = RuleTaskPhase


class RuleSeverity(StrEnum):
    """Urgency and precedence level of a rule."""

    MANDATORY = "mandatory"
    RECOMMENDED = "recommended"
    ADVISORY = "advisory"


@dataclass(frozen=True)
class PathScope:
    """Glob patterns defining when a rule applies."""

    include_patterns: list[str] = field(default_factory=lambda: ["*"])
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuleItem:
    """A scoped rule with targeting criteria and content."""

    rule_id: str
    title: str
    content: str
    scope: PathScope = field(default_factory=PathScope)
    applicable_phases: set[TaskPhase] = field(
        default_factory=lambda: {
            TaskPhase.INTENT,
            TaskPhase.SPEC,
            TaskPhase.PLAN,
            TaskPhase.CODE,
            TaskPhase.TEST,
            TaskPhase.REVIEW,
        }
    )
    severity: RuleSeverity = RuleSeverity.MANDATORY
    conflict_keys: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ActiveWorkingSet:
    """Current focus of agent execution."""

    active_paths: list[str] = field(default_factory=list)
    current_phase: TaskPhase = TaskPhase.CODE


@dataclass
class RuleTelemetryRecord:
    """Invocation and matching telemetry for a rule."""

    rule_id: str
    hits_count: int = 0
    last_matched_phase: TaskPhase | None = None
    matched_paths: set[str] = field(default_factory=set)
    is_archived: bool = False


@dataclass(frozen=True)
class EntropyConflictItem:
    """Identified conflict between two or more rules."""

    conflict_key: str
    competing_rule_ids: list[str]
    description: str


@dataclass(frozen=True)
class EntropyAuditReport:
    """Result of architecture entropy draining sweep."""

    total_rules_inspected: int
    active_rules_retained: int
    stale_rules_archived: list[str]
    detected_conflicts: list[EntropyConflictItem]
    pruning_efficiency_ratio: float
