"""Unified orchestration facade for hierarchical rules and glob-scoped matching.

[INPUT]
- AttentionAuditReport, HierarchicalRulesConfig, RuleFileDescriptor, RuleMatchResult, RuleTierKind:
  Domain types from rule_types.

[OUTPUT]
- HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite: Unified orchestration facade
  managing 3-tier precedence, glob-scoped activation, transclusions, and 200-line health guards.

[POS]
Top-level entrypoint for hierarchical rule decoupling and attention dilution defense.
"""

from __future__ import annotations

import os
from typing import Mapping, Sequence

from .attention_dilution_guard import audit_rule_attention_health
from .glob_rule_matcher import match_rules_against_targets, parse_rule_frontmatter
from .rule_transclusion_engine import resolve_rule_transclusions
from .rule_types import (
    AttentionAuditReport,
    HierarchicalRulesConfig,
    RuleFileDescriptor,
    RuleMatchResult,
    RuleTierKind,
)


class HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite:
    """Orchestrates 3-tier rules hierarchy, glob activation, transclusions, and attention audits."""

    def __init__(self, config: HierarchicalRulesConfig | None = None) -> None:
        self._config = config or HierarchicalRulesConfig()
        self._registered_rules: list[RuleFileDescriptor] = []

    @property
    def config(self) -> HierarchicalRulesConfig:
        return self._config

    def register_rule(
        self,
        file_path: str,
        tier: RuleTierKind,
        content: str,
        file_reader_mock: Mapping[str, str] | None = None,
    ) -> RuleFileDescriptor:
        """Register and parse a rule file into the suite with frontmatter and transclusions."""
        globs, body = parse_rule_frontmatter(content)
        resolved_body = body
        transclusions: list[str] = []

        if self._config.enable_transclusion:
            resolved_body, transclusions = resolve_rule_transclusions(
                base_file_path=file_path,
                raw_content=body,
                file_reader=file_reader_mock,
            )

        lines = resolved_body.splitlines()
        descriptor = RuleFileDescriptor(
            file_path=file_path,
            tier=tier,
            name=os.path.basename(file_path),
            glob_patterns=globs,
            raw_content=content,
            resolved_content=resolved_body,
            line_count=len(lines),
            transclusions=transclusions,
        )
        self._registered_rules.append(descriptor)
        return descriptor

    def match_and_assemble(
        self,
        target_files: Sequence[str],
    ) -> RuleMatchResult:
        """Match rules against current target files and assemble stratified prompt.

        Precedence order:
        1. USER_GLOBAL: Baseline preferences.
        2. PROJECT_SHARED: Team and project conventions.
        3. LOCAL_OVERRIDE: Private developer overrides (highest priority).
        """
        active_rules, suppressed_rules = match_rules_against_targets(
            self._registered_rules,
            target_files,
        )

        # Sort active rules by tier precedence
        tier_weights = {
            RuleTierKind.USER_GLOBAL: 1,
            RuleTierKind.PROJECT_SHARED: 2,
            RuleTierKind.LOCAL_OVERRIDE: 3,
        }
        sorted_active = sorted(active_rules, key=lambda r: tier_weights.get(r.tier, 0))

        # Calculate estimated token savings from suppressed rules
        suppressed_chars = sum(len(r.resolved_content) for r in suppressed_rules)
        total_chars = sum(len(r.resolved_content) for r in self._registered_rules)
        savings_pct = 0.0
        if total_chars > 0:
            savings_pct = round((suppressed_chars / float(total_chars)) * 100.0, 1)

        # Assemble prompt with tier demarcation headers
        prompt_sections: list[str] = []
        for rule in sorted_active:
            header = f"### [RULE TIER: {rule.tier.value.upper()}] {rule.name}"
            if rule.glob_patterns:
                header += f" (Scoped: {', '.join(rule.glob_patterns)})"
            prompt_sections.append(f"{header}\n{rule.resolved_content.strip()}")

        assembled = "\n\n".join(prompt_sections)

        all_matched_globs: list[str] = []
        for r in sorted_active:
            all_matched_globs.extend(r.glob_patterns)

        return RuleMatchResult(
            active_rules=sorted_active,
            matched_globs=all_matched_globs,
            suppressed_count=len(suppressed_rules),
            assembled_prompt=assembled,
            token_savings_percent=savings_pct,
        )

    def audit_attention_dilution(self) -> list[AttentionAuditReport]:
        """Audit all registered rules against the 200-line attention preservation threshold."""
        reports: list[AttentionAuditReport] = []
        for r in self._registered_rules:
            report = audit_rule_attention_health(
                file_path=r.file_path,
                content=r.resolved_content,
                max_lines=self._config.max_line_limit,
            )
            reports.append(report)
        return reports

    def clear(self) -> None:
        """Clear all registered rules."""
        self._registered_rules.clear()

    @classmethod
    def create(
        cls,
        config: HierarchicalRulesConfig | None = None,
    ) -> HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite:
        """Create a default suite instance."""
        return cls(config)
