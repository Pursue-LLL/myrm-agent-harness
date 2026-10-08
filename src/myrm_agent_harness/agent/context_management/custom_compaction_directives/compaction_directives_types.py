"""Data contracts and type definitions for custom compaction directives and preservation whitelist.

Enables user-defined compaction preservation rules (e.g. from CLAUDE.md or project settings),
prompt slot injection, post-compaction integrity auditing, and automatic self-healing patches.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- PreservationDirectiveKind: Categorization of preservation rules enforced during session compaction.
- PreservationDirective: Individual custom preservation rule governing context summarization.
- DirectiveAuditResult: Audit verification outcome for a single preservation directive.
- CompactionIntegrityReport: Comprehensive integrity score verifying custom directives retention
  post-compaction.
- CustomCompactionConfig: Operational settings for user directives injection and auditing.

[POS]
Data contracts and type definitions for custom compaction directives and preservation whitelist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PreservationDirectiveKind(str, Enum):
    """Categorization of preservation rules enforced during session compaction."""

    MUST_PRESERVE_VERBATIM = "must_preserve_verbatim"
    PRESERVE_IDENTIFIER = "preserve_identifier"
    PRESERVE_DECISION = "preserve_decision"
    PRESERVE_TODO = "preserve_todo"
    CUSTOM_RULE = "custom_rule"


@dataclass(frozen=True)
class PreservationDirective:
    """Individual custom preservation rule governing context summarization."""

    directive_id: str
    kind: PreservationDirectiveKind
    instruction: str
    required_keywords: list[str] = field(default_factory=list)
    required_entities: list[str] = field(default_factory=list)
    priority: int = 100


@dataclass(frozen=True)
class DirectiveAuditResult:
    """Audit verification outcome for a single preservation directive."""

    directive_id: str
    is_satisfied: bool
    missing_entities: list[str] = field(default_factory=list)
    matched_snippets: list[str] = field(default_factory=list)
    explanation: str = ""


@dataclass(frozen=True)
class CompactionIntegrityReport:
    """Comprehensive integrity score verifying custom directives retention post-compaction."""

    session_id: str
    total_directives: int
    satisfied_count: int
    missing_count: int
    retention_rate: float
    was_healed: bool
    audit_details: list[DirectiveAuditResult] = field(default_factory=list)
    healed_entities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CustomCompactionConfig:
    """Operational settings for user directives injection and auditing."""

    strict_audit: bool = True
    auto_heal_missing: bool = True
    min_acceptable_retention_rate: float = 0.90
