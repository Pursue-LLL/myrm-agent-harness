# [INPUT]: None
# [OUTPUT]: RuleTierKind, RuleFileDescriptor, RuleMatchResult, AttentionAuditReport, HierarchicalRulesConfig
# [POS]: agent/context_management/hierarchical_rules/rule_types.py

"""Domain contracts and models for hierarchical rule decoupling and glob-scoped matching.

[INPUT]
- None (Self-contained strongly-typed contracts).

[OUTPUT]
- RuleTierKind: Classification of rule tier (user global, project shared, local override).
- RuleFileDescriptor: Parsed rule document with metadata and transclusion references.
- RuleMatchResult: Evaluated dynamic rule match outcome with assembled prompt.
- AttentionAuditReport: Diagnostic health audit evaluating 200-line dilution thresholds.
- HierarchicalRulesConfig: Configuration options for rule loading and enforcement.

[POS]
Domain models for multi-tier rules directory, glob matching, and attention dilution defense.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class RuleTierKind(str, Enum):
    """Hierarchy precedence level for rule scoping."""

    USER_GLOBAL = "user_global"
    PROJECT_SHARED = "project_shared"
    LOCAL_OVERRIDE = "local_override"


@dataclass(frozen=True)
class RuleFileDescriptor:
    """Parsed rule specification with frontmatter scoping and line metrics."""

    file_path: str
    tier: RuleTierKind
    name: str
    glob_patterns: Sequence[str] = field(default_factory=list)
    raw_content: str = ""
    resolved_content: str = ""
    line_count: int = 0
    transclusions: Sequence[str] = field(default_factory=list)
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleMatchResult:
    """Outcome of evaluating dynamic glob scopes against active session target files."""

    active_rules: Sequence[RuleFileDescriptor]
    matched_globs: Sequence[str]
    suppressed_count: int
    assembled_prompt: str
    token_savings_percent: float = 0.0


@dataclass(frozen=True)
class AttentionAuditReport:
    """Diagnostic health assessment guarding against attention dilution beyond 200 lines."""

    file_path: str
    line_count: int
    is_diluted: bool
    risk_score: float
    split_recommendation: str | None = None


@dataclass(frozen=True)
class HierarchicalRulesConfig:
    """Operational settings for rule hierarchy and attention constraints."""

    max_line_limit: int = 200
    user_rules_dir: str | None = None
    project_rules_dir: str | None = None
    local_override_path: str | None = None
    enable_transclusion: bool = True
