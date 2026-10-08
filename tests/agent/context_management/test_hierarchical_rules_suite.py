# [INPUT]: AttentionAuditReport, HierarchicalRulesConfig, HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite, RuleFileDescriptor, RuleMatchResult, RuleTierKind
# [OUTPUT]: test_three_tier_rule_hierarchy_precedence_and_overrides, test_glob_scoped_dynamic_rule_matching_and_token_savings, test_rule_transclusion_inlining_and_cycle_prevention, test_attention_dilution_guard_200_line_limit_and_recommendations
# [POS]: tests/agent/context_management/test_hierarchical_rules_suite.py

"""Comprehensive test suite for hierarchical rule decoupling, glob scoping, transclusions, and attention defense.

Validates:
1. Three-tier rule hierarchy precedence (User Global -> Project Shared -> Local Override).
2. Glob-scoped dynamic rule matcher selective mounting and token reduction for unassociated domains.
3. Rule transclusion engine (@path) recursive inlining and circular reference cycle protection.
4. Attention dilution guard enforcing 200-line health limits and decomposition guidance.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.hierarchical_rules import (
    AttentionAuditReport,
    HierarchicalRulesConfig,
    HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite,
    RuleFileDescriptor,
    RuleMatchResult,
    RuleTierKind,
    audit_rule_attention_health,
)


def test_three_tier_rule_hierarchy_precedence_and_overrides() -> None:
    """Validate 3-tier precedence ordering: User Global -> Project Shared -> Local Override."""
    suite = HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite.create()

    suite.register_rule(
        file_path="~/.myrm/rules/global_format.md",
        tier=RuleTierKind.USER_GLOBAL,
        content="# Global User Prefs\nAlways use 4 spaces indentation.",
    )
    suite.register_rule(
        file_path=".myrm/rules.local.md",
        tier=RuleTierKind.LOCAL_OVERRIDE,
        content="# Local Override\nFor this repo use 2 spaces indentation.",
    )
    suite.register_rule(
        file_path=".myrm/rules/project_shared.md",
        tier=RuleTierKind.PROJECT_SHARED,
        content="# Project Shared\nFollow PEP8 naming conventions.",
    )

    match_res = suite.match_and_assemble(target_files=["src/main.py"])

    assert len(match_res.active_rules) == 3
    # Check ordering by precedence
    assert match_res.active_rules[0].tier == RuleTierKind.USER_GLOBAL
    assert match_res.active_rules[1].tier == RuleTierKind.PROJECT_SHARED
    assert match_res.active_rules[2].tier == RuleTierKind.LOCAL_OVERRIDE

    # Local override must appear at the tail (highest priority in LLM context flow)
    assert "[RULE TIER: LOCAL_OVERRIDE] rules.local.md" in match_res.assembled_prompt
    assert "For this repo use 2 spaces indentation." in match_res.assembled_prompt


def test_glob_scoped_dynamic_rule_matching_and_token_savings() -> None:
    """Validate glob-scoped rule activation and token savings from suppressing unrelated domains."""
    suite = HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite.create()

    # Universal rule (no glob -> always active)
    suite.register_rule(
        file_path=".myrm/rules/universal.md",
        tier=RuleTierKind.PROJECT_SHARED,
        content="# Core Invariants\nNever modify external system configuration.",
    )

    # Frontend scoped rule
    fe_content = """---
paths: ["src/frontend/**", "web/**/*.tsx"]
---
# React UI Rules
Use functional components and strictly typed props interfaces.
"""
    suite.register_rule(
        file_path=".myrm/rules/frontend.md",
        tier=RuleTierKind.PROJECT_SHARED,
        content=fe_content,
    )

    # Billing database scoped rule
    db_content = """---
paths: ["src/billing/**", "app/database/**"]
---
# Database Safety
Always execute DDL migrations inside transactions and require down migration scripts.
"""
    suite.register_rule(
        file_path=".myrm/rules/billing_db.md",
        tier=RuleTierKind.PROJECT_SHARED,
        content=db_content,
    )

    # Scenario A: Editing frontend component only
    res_fe = suite.match_and_assemble(target_files=["src/frontend/components/Header.tsx"])
    active_names_fe = [r.name for r in res_fe.active_rules]
    assert "universal.md" in active_names_fe
    assert "frontend.md" in active_names_fe
    assert "billing_db.md" not in active_names_fe
    assert res_fe.suppressed_count == 1
    assert res_fe.token_savings_percent > 0.0
    assert "React UI Rules" in res_fe.assembled_prompt
    assert "Database Safety" not in res_fe.assembled_prompt

    # Scenario B: Editing billing migration only
    res_db = suite.match_and_assemble(target_files=["src/billing/migrations/001_tax.py"])
    active_names_db = [r.name for r in res_db.active_rules]
    assert "universal.md" in active_names_db
    assert "billing_db.md" in active_names_db
    assert "frontend.md" not in active_names_db
    assert res_db.suppressed_count == 1
    assert "Database Safety" in res_db.assembled_prompt
    assert "React UI Rules" not in res_db.assembled_prompt


def test_rule_transclusion_inlining_and_cycle_prevention() -> None:
    """Validate recursive rule transclusion (@path) and circular reference guard."""
    mock_files = {
        "shared/security_baseline.md": "### Security Baseline\nSanitize all inputs before execution.",
        "cycle_a.md": "Rules A includes @cycle_b.md",
        "cycle_b.md": "Rules B includes @cycle_a.md",
    }

    suite = HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite.create()

    # Normal transclusion test
    parent_rule = """# Project Guidelines
Refer to common security standards:
@shared/security_baseline.md
All team members must comply.
"""
    desc = suite.register_rule(
        file_path=".myrm/rules/root.md",
        tier=RuleTierKind.PROJECT_SHARED,
        content=parent_rule,
        file_reader_mock=mock_files,
    )

    assert "shared/security_baseline.md" in desc.transclusions
    assert "Begin transclusion: @shared/security_baseline.md" in desc.resolved_content
    assert "Sanitize all inputs before execution." in desc.resolved_content

    # Circular transclusion protection
    suite_cycle = HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite.create()
    cycle_desc = suite_cycle.register_rule(
        file_path="cycle_a.md",
        tier=RuleTierKind.PROJECT_SHARED,
        content=mock_files["cycle_a.md"],
        file_reader_mock=mock_files,
    )

    # Verification: Must prevent infinite recursion and emit cycle warning comment
    assert "Transclusion cycle prevented" in cycle_desc.resolved_content


def test_attention_dilution_guard_200_line_limit_and_recommendations() -> None:
    """Validate 200-line attention limit inspection, risk scoring, and decomposition guidance."""
    # 1. Healthy concise rule
    short_content = "\n".join([f"Line {i}: Do something safely." for i in range(50)])
    rep_short = audit_rule_attention_health("concise.md", short_content, max_lines=200)
    assert rep_short.is_diluted is False
    assert rep_short.line_count == 50
    assert rep_short.risk_score == 0.0
    assert rep_short.split_recommendation is None

    # 2. Moderately bloated rule (250 lines -> excess 50)
    bloated_content = "\n".join([f"Rule {i}: Specification line." for i in range(250)])
    rep_bloated = audit_rule_attention_health("monolithic_agents.md", bloated_content, max_lines=200)
    assert rep_bloated.is_diluted is True
    assert rep_bloated.line_count == 250
    assert rep_bloated.risk_score == 0.25  # 50 / 200 = 0.25
    assert rep_bloated.split_recommendation is not None
    assert "exceeding the 200-line attention limit" in rep_bloated.split_recommendation

    # 3. Severely bloated rule (450 lines -> excess 250 -> max risk capped at 1.0)
    severe_content = "\n".join([f"Rule {i}: Heavy specification." for i in range(450)])
    rep_severe = audit_rule_attention_health("giant_agents.md", severe_content, max_lines=200)
    assert rep_severe.is_diluted is True
    assert rep_severe.risk_score == 1.0

    # 4. Suite integration audit
    suite = HierarchicalRulesDirectoryAndGlobScopedDynamicRuleMatcherSuite.create()
    suite.register_rule("r1.md", RuleTierKind.PROJECT_SHARED, short_content)
    suite.register_rule("r2.md", RuleTierKind.PROJECT_SHARED, bloated_content)

    audits = suite.audit_attention_dilution()
    assert len(audits) == 2
    assert audits[0].is_diluted is False
    assert audits[1].is_diluted is True
