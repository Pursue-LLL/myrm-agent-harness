# [INPUT]: rule_types, glob_rule_matcher, rule_transclusion_engine, attention_dilution_guard, hierarchical_rules_suite
# [OUTPUT]: AttentionAuditReport, HierarchicalRulesConfig, HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite, RuleFileDescriptor, RuleMatchResult, RuleTierKind, audit_rule_attention_health, batch_audit_rules, is_rule_active_for_targets, match_rules_against_targets, parse_rule_frontmatter, resolve_rule_transclusions
# [POS]: agent/context_management/hierarchical_rules/__init__.py

"""Hierarchical rules directory decoupling, glob-scoped matching, and attention defense package.

[INPUT]
- rule_types: Domain contracts, tier definitions, and metrics.
- glob_rule_matcher: Frontmatter parsing and path glob matching.
- rule_transclusion_engine: Single-source inline @path transclusions.
- attention_dilution_guard: 200-line health auditing and split recommendations.
- hierarchical_rules_suite: Unified orchestration facade.

[OUTPUT]
- Canonical exports for hierarchical rule subsystem.

[POS]
Modular implementation of 3-tier rule hierarchy, dynamic glob scoping, transclusions, and attention defense.
"""

from __future__ import annotations

from .attention_dilution_guard import audit_rule_attention_health, batch_audit_rules
from .glob_rule_matcher import (
    is_rule_active_for_targets,
    match_rules_against_targets,
    parse_rule_frontmatter,
)
from .hierarchical_rules_suite import (
    HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite,
)
from .rule_transclusion_engine import (
    extract_transclusion_paths,
    resolve_rule_transclusions,
)
from .rule_types import (
    AttentionAuditReport,
    HierarchicalRulesConfig,
    RuleFileDescriptor,
    RuleMatchResult,
    RuleTierKind,
)

__all__ = [
    "AttentionAuditReport",
    "HierarchicalRulesConfig",
    "HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite",
    "RuleFileDescriptor",
    "RuleMatchResult",
    "RuleTierKind",
    "audit_rule_attention_health",
    "batch_audit_rules",
    "extract_transclusion_paths",
    "is_rule_active_for_targets",
    "match_rules_against_targets",
    "parse_rule_frontmatter",
    "resolve_rule_transclusions",
]
