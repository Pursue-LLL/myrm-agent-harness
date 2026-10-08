"""Unit tests for ClaudeCodeProjectInstructionsPrecedenceSuite and 4-mode filtering."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.workspace_rules import (
    ClaudeCodeProjectInstructionsPrecedenceSuite,
    InstructionMode,
    InstructionSettings,
    PrecedenceAuditReceipt,
    RuleFile,
    SettingsScope,
)


def _build_dummy_rule(path: str, content: str = "Dummy instruction") -> RuleFile:
    return RuleFile(
        path=path,
        content=content,
        source=path,
        truncated=False,
        blocked=False,
    )


def test_repo_has_no_authority_precedence_rejection() -> None:
    """Test repository settings cannot override instruction mode, and repo_override_rejected is flagged."""
    suite = ClaudeCodeProjectInstructionsPrecedenceSuite()

    # Repo attempts to force ONLY_CLAUDE
    repo_settings = InstructionSettings(
        mode=InstructionMode.ONLY_CLAUDE,
        scope=SettingsScope.REPO_CONFIG,
    )

    # User configured ALL_MERGED
    user_settings = InstructionSettings(
        mode=InstructionMode.ALL_MERGED,
        scope=SettingsScope.USER_SETTINGS,
    )

    scanned_rules = [
        _build_dummy_rule("CLAUDE.md", "Claude rules"),
        _build_dummy_rule("AGENTS.md", "Agents rules"),
    ]

    rules, receipt = suite.resolve_and_filter_rules(
        scanned_rules=scanned_rules,
        user_settings=user_settings,
        repo_settings=repo_settings,
    )

    # Repo override must be rejected
    assert receipt.repo_override_rejected is True
    assert receipt.effective_mode == InstructionMode.ALL_MERGED
    assert receipt.origin_scope == SettingsScope.USER_SETTINGS
    # Under ALL_MERGED, both rules remain
    assert len(rules) == 2


def test_instruction_mode_only_managed_blocks_repo_files() -> None:
    """Test ONLY_MANAGED mode strictly suppresses all repository rule files and keeps managed instructions."""
    suite = ClaudeCodeProjectInstructionsPrecedenceSuite()

    managed_settings = InstructionSettings(
        mode=InstructionMode.ONLY_MANAGED,
        scope=SettingsScope.MANAGED_SETTINGS,
        managed_instructions=["Enterprise mandatory compliance constraint"],
    )

    scanned_rules = [
        _build_dummy_rule("CLAUDE.md", "Local Claude rules"),
        _build_dummy_rule("AGENTS.md", "Local Agents rules"),
        _build_dummy_rule(".myrm/rules/custom.md", "Custom rules"),
    ]

    rules, receipt = suite.resolve_and_filter_rules(
        scanned_rules=scanned_rules,
        managed_settings=managed_settings,
    )

    assert receipt.effective_mode == InstructionMode.ONLY_MANAGED
    assert receipt.origin_scope == SettingsScope.MANAGED_SETTINGS
    # All 3 local rules suppressed, only 1 managed rule retained
    assert receipt.suppressed_rules_count == 3
    assert len(rules) == 1
    assert rules[0].source == "MANAGED_SETTINGS"
    assert "Enterprise mandatory compliance constraint" in rules[0].content


def test_instruction_mode_fallback_default_claude_over_agents() -> None:
    """Test FALLBACK_DEFAULT mode matches Claude Code 2.1.277 single-file fallback semantics."""
    suite = ClaudeCodeProjectInstructionsPrecedenceSuite()

    user_settings = InstructionSettings(
        mode=InstructionMode.FALLBACK_DEFAULT,
        scope=SettingsScope.USER_SETTINGS,
    )

    # Scenario A: Both CLAUDE.md and AGENTS.md exist -> CLAUDE.md wins, AGENTS.md suppressed
    scanned_both = [
        _build_dummy_rule("CLAUDE.md", "Claude rules"),
        _build_dummy_rule("AGENTS.md", "Agents rules"),
    ]
    rules_a, receipt_a = suite.resolve_and_filter_rules(
        scanned_rules=scanned_both,
        user_settings=user_settings,
    )
    assert len(rules_a) == 1
    assert rules_a[0].path == "CLAUDE.md"
    assert receipt_a.suppressed_rules_count == 1

    # Scenario B: Only AGENTS.md exists -> AGENTS.md fallback selected
    scanned_only_agents = [
        _build_dummy_rule("AGENTS.md", "Agents fallback rules"),
    ]
    rules_b, receipt_b = suite.resolve_and_filter_rules(
        scanned_rules=scanned_only_agents,
        user_settings=user_settings,
    )
    assert len(rules_b) == 1
    assert rules_b[0].path == "AGENTS.md"
    assert receipt_b.suppressed_rules_count == 0


def test_instruction_mode_all_merged_and_only_filters() -> None:
    """Test ALL_MERGED, ONLY_CLAUDE, and ONLY_AGENTS mode filters with managed instructions synthesis."""
    suite = ClaudeCodeProjectInstructionsPrecedenceSuite()

    scanned_rules = [
        _build_dummy_rule("CLAUDE.md", "Claude rules"),
        _build_dummy_rule("AGENTS.md", "Agents rules"),
        _build_dummy_rule(".cursorrules", "Cursor rules"),
    ]

    managed_settings = InstructionSettings(
        mode=InstructionMode.ALL_MERGED,
        scope=SettingsScope.MANAGED_SETTINGS,
        managed_instructions=["Global corporate instruction"],
    )

    # 1. ALL_MERGED: 1 managed + 3 local = 4 rules
    rules_merged, receipt_merged = suite.resolve_and_filter_rules(
        scanned_rules=scanned_rules,
        managed_settings=managed_settings,
    )
    assert len(rules_merged) == 4
    assert rules_merged[0].source == "MANAGED_SETTINGS"

    # 2. ONLY_CLAUDE: 1 managed + 1 CLAUDE = 2 rules
    settings_claude = InstructionSettings(
        mode=InstructionMode.ONLY_CLAUDE,
        scope=SettingsScope.USER_SETTINGS,
        managed_instructions=["Global corporate instruction"],
    )
    rules_claude, receipt_claude = suite.resolve_and_filter_rules(
        scanned_rules=scanned_rules,
        user_settings=settings_claude,
    )
    assert len(rules_claude) == 2
    assert rules_claude[0].source == "MANAGED_SETTINGS"
    assert rules_claude[1].path == "CLAUDE.md"

    # 3. ONLY_AGENTS: 1 managed + 1 AGENTS = 2 rules
    settings_agents = InstructionSettings(
        mode=InstructionMode.ONLY_AGENTS,
        scope=SettingsScope.USER_SETTINGS,
        managed_instructions=["Global corporate instruction"],
    )
    rules_agents, _ = suite.resolve_and_filter_rules(
        scanned_rules=scanned_rules,
        user_settings=settings_agents,
    )
    assert len(rules_agents) == 2
    assert rules_agents[0].source == "MANAGED_SETTINGS"
    assert rules_agents[1].path == "AGENTS.md"
