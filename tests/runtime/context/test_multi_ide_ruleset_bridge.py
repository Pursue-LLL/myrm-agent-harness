"""Tests for Multi-IDE Universal Ruleset Parser and Trae Rules Compatibility Bridge."""

from __future__ import annotations

from myrm_agent_harness.runtime.context.multi_ide_ruleset_bridge import (
    IdeEcosystemClassifier,
    IdeEcosystemKind,
    MultiIdeRulesetBridge,
)


def test_ide_ecosystem_classifier():
    trae_kind, trae_weight = IdeEcosystemClassifier.classify("/project/.trae/rules/clean_code.md")
    assert trae_kind == IdeEcosystemKind.TRAE
    assert trae_weight == 80

    traerules_kind, traerules_weight = IdeEcosystemClassifier.classify("/project/.traerules")
    assert traerules_kind == IdeEcosystemKind.TRAE
    assert traerules_weight == 80

    cursor_kind, cursor_weight = IdeEcosystemClassifier.classify("/project/.cursor/rules/style.mdc")
    assert cursor_kind == IdeEcosystemKind.CURSOR
    assert cursor_weight == 70

    claude_kind, _ = IdeEcosystemClassifier.classify("/project/CLAUDE.md")
    assert claude_kind == IdeEcosystemKind.CLAUDE

    goose_kind, _ = IdeEcosystemClassifier.classify("/project/.goosehints")
    assert goose_kind == IdeEcosystemKind.GOOSE

    myrm_kind, myrm_weight = IdeEcosystemClassifier.classify("/project/.myrm/rules/security.md")
    assert myrm_kind == IdeEcosystemKind.MYRM
    assert myrm_weight == 100


def test_parse_rule_file_with_frontmatter_and_checksum():
    raw_content = (
        "---\n"
        "name: python_standards\n"
        "globs: ['*.py', '*.pyi']\n"
        "---\n"
        "Always use PEP 8 and Python 3.13 features.\n"
    )
    rule = MultiIdeRulesetBridge.parse_rule_file(
        file_path="/repo/.trae/rules/standards.md",
        raw_content=raw_content,
    )

    assert rule.ecosystem == IdeEcosystemKind.TRAE
    assert rule.rule_name == "standards.md"
    assert rule.globs == ("*.py", "*.pyi")
    assert rule.content == "Always use PEP 8 and Python 3.13 features."
    assert len(rule.checksum_sha256) == 64


def test_scan_workspace_multi_ecosystems(tmp_path):
    workspace = tmp_path / "cross_ide_repo"
    workspace.mkdir()

    # Trae rules directory
    trae_dir = workspace / ".trae" / "rules"
    trae_dir.mkdir(parents=True)
    (trae_dir / "style.md").write_text("Trae style rule.")

    # Cursor root rule
    (workspace / ".cursorrules").write_text("Cursor root rule.")

    # Goose hints
    (workspace / ".goosehints").write_text("Goose hints rule.")

    rules = MultiIdeRulesetBridge.scan_workspace(str(workspace))
    assert len(rules) == 3

    ecosystems = {r.ecosystem for r in rules}
    assert IdeEcosystemKind.TRAE in ecosystems
    assert IdeEcosystemKind.CURSOR in ecosystems
    assert IdeEcosystemKind.GOOSE in ecosystems


def test_deduplicate_and_prioritize_by_checksum_and_name():
    # Identical content in Trae vs Cursor: Trae (weight 80) should win over Cursor (weight 70)
    identical_content = "Format all code with ruff format."

    trae_rule = MultiIdeRulesetBridge.parse_rule_file(
        file_path="/repo/.trae/rules/format.md",
        raw_content=identical_content,
    )
    cursor_rule = MultiIdeRulesetBridge.parse_rule_file(
        file_path="/repo/.cursorrules",
        raw_content=identical_content,
    )

    # Different rule with distinct content
    goose_rule = MultiIdeRulesetBridge.parse_rule_file(
        file_path="/repo/.goosehints",
        raw_content="Distinct goose hints for CLI.",
    )

    deduped = MultiIdeRulesetBridge.deduplicate_and_prioritize(
        [cursor_rule, trae_rule, goose_rule]
    )

    assert len(deduped) == 2
    # Winner between Trae and Cursor is Trae
    assert deduped[0].ecosystem == IdeEcosystemKind.TRAE
    assert deduped[0].content == identical_content
    # Followed by Goose
    assert deduped[1].ecosystem == IdeEcosystemKind.GOOSE


def test_migration_readiness_report_generation():
    rule1 = MultiIdeRulesetBridge.parse_rule_file("/repo/.traerules", "Rule A")
    rule2 = MultiIdeRulesetBridge.parse_rule_file("/repo/.cursorrules", "Rule A")  # Duplicate content
    rule3 = MultiIdeRulesetBridge.parse_rule_file("/repo/.goosehints", "Rule B")

    report = MultiIdeRulesetBridge.generate_migration_readiness_report([rule1, rule2, rule3])

    assert report.total_rules_scanned == 3
    assert report.effective_rules_count == 2
    assert report.deduplicated_count == 1
    assert report.compatibility_score == 2 / 3
    assert "生态迁移就绪度: 100% 兼容" in report.readiness_summary_banner
    assert report.ecosystem_breakdown[IdeEcosystemKind.TRAE.value] == 1
    assert report.ecosystem_breakdown[IdeEcosystemKind.CURSOR.value] == 1
    assert report.ecosystem_breakdown[IdeEcosystemKind.GOOSE.value] == 1


def test_render_unified_rules_xml():
    r1 = MultiIdeRulesetBridge.parse_rule_file("/repo/.traerules", "Strict typing enforced.")
    xml = MultiIdeRulesetBridge.render_unified_rules_xml([r1])

    assert '<multi_ide_project_rules version="1.0">' in xml
    assert '<summary total_rules="1" />' in xml
    assert '<rule name=".traerules" ecosystem="trae" priority="80">' in xml
    assert "Strict typing enforced." in xml
    assert "</multi_ide_project_rules>" in xml
