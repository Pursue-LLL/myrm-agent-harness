# [INPUT]: ConflictArbitrationResult, DriftAuditReport, ExceptionAwareRuleParser, MemoryFileConflictArbiter, ParsedRuleClause, PersistentContextRuleDriftAuditAndExceptionAwareGovernanceSuite, RuleCallerContext, RuleDriftAndSecretProbe, RuleGovernanceConfig, RuleSecretScanResult, ShadowedRuleFinding
# [OUTPUT]: test_persistent_rule_governance_suite.py
# [POS]: tests/agent/workspace_rules/test_persistent_rule_governance_suite.py

"""Unit test suite for PersistentContextRuleDriftAuditAndExceptionAwareGovernanceSuite.

Verifies:
1. Exception-aware rule schema parsing and caller watchdog exemption evaluation.
2. SSOT memory-file conflict arbitration and reference pointer generation.
3. Pre-flight rule secret scrubbing and confidentiality tier protection.
4. Low-peak rule drift inspection against repository files and toolchain manifest.
5. Sibling file shadowing audit and end-to-end governed text preparation.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.workspace_rules.rule_governance import (
    ConflictArbitrationResult,
    DriftAuditReport,
    ExceptionAwareRuleParser,
    MemoryFileConflictArbiter,
    ParsedRuleClause,
    PersistentContextRuleDriftAuditAndExceptionAwareGovernanceSuite,
    RuleCallerContext,
    RuleDriftAndSecretProbe,
    RuleGovernanceConfig,
    RuleSecretScanResult,
    ShadowedRuleFinding,
)


def test_exception_aware_rule_parsing_and_watchdog_exemption() -> None:
    parser = ExceptionAwareRuleParser()

    markdown_rules = """
# Project Operation Discipline
- 严禁未经确认重启后台服务【例外】：系统后台健康看门狗执行自动恢复除外
- NEVER drop production database tables [EXCEPTION]: automated CI teardown in ephemeral sandboxes
- 常规建议：代码提交前进行静态检查
"""
    clauses = parser.parse_document(markdown_rules)
    assert len(clauses) == 3

    clause1 = clauses[0]
    assert clause1.is_strict is True
    assert "严禁未经确认重启后台服务" in clause1.core_directive
    assert len(clause1.exceptions) == 1
    assert "系统后台健康看门狗执行自动恢复除外" in clause1.exceptions[0]

    # Human user initiating restart -> Blocked
    human_caller = RuleCallerContext(initiator="developer_alice", is_system_watchdog=False)
    permitted, reason = parser.evaluate_action_permitted(
        clause1, human_caller, action_description="Restart backend service immediately"
    )
    assert permitted is False
    assert "Blocked" in reason

    # Watchdog initiator executing recovery -> Exempted
    watchdog_caller = RuleCallerContext(initiator="health_watchdog", is_system_watchdog=True)
    permitted_wd, reason_wd = parser.evaluate_action_permitted(
        clause1, watchdog_caller, action_description="Restart backend service after crash"
    )
    assert permitted_wd is True
    assert "Exempted: Watchdog caller" in reason_wd

    # English exception matching
    clause2 = clauses[1]
    assert clause2.is_strict is True
    ci_caller = RuleCallerContext(initiator="ci_runner")
    permitted_ci, _ = parser.evaluate_action_permitted(
        clause2, ci_caller, action_description="automated CI teardown in ephemeral sandboxes"
    )
    assert permitted_ci is True

    # Non-strict guideline -> Always permitted
    clause3 = clauses[2]
    assert clause3.is_strict is False
    perm3, _ = parser.evaluate_action_permitted(clause3, human_caller, "skip static check")
    assert perm3 is True


def test_memory_file_conflict_arbitration() -> None:
    arbiter = MemoryFileConflictArbiter(RuleGovernanceConfig(file_ssot_authoritative=True))

    memory_key = "user_preference_test_command"
    memory_fact = "Use bun test to run all test suites"
    memory_mtime = 1710000500.0  # newer timestamp

    rule_path = "/workspace/AGENTS.md"
    rule_content = "Run tests with: npm test"
    file_mtime = 1710000100.0  # older timestamp

    result = arbiter.arbitrate_conflict(
        memory_key=memory_key,
        memory_fact=memory_fact,
        memory_mtime=memory_mtime,
        rule_file_path=rule_path,
        rule_content=rule_content,
        file_mtime=file_mtime,
    )

    # In SSOT file-authoritative mode, workspace file always governs active execution
    assert result.winner == "file"
    assert "authoritative SSOT" in result.arbitration_reason
    assert "已优先遵循权威工作区规则文件《AGENTS.md》" in result.alert_message

    # Pointer generation test
    pointer = arbiter.build_rule_reference_pointer(rule_path, "a1b2c3d4e5f67890abcdef")
    assert pointer == "rule_ref@/workspace/AGENTS.md:a1b2c3d4e5f6"


def test_rule_secret_scrubbing_and_confidentiality_tier() -> None:
    probe = RuleDriftAndSecretProbe()

    text_with_secrets = """
    # Deployment Rules
    - Deploy using token sk-ant-api03-abcdef123456789012345678901234567890
    - Push with ghp_111122223333444455556666777788889999
    - Safe line: use standard git checkout
    """

    res = probe.sanitize_secrets_in_content(text_with_secrets)
    assert res.has_violation is True
    assert "sk-ant" not in res.redacted_content
    assert "ghp_" not in res.redacted_content
    assert "[REDACTED_CREDENTIAL:" in res.redacted_content
    assert res.alert_banner is not None
    assert "载入域保密越界" in res.alert_banner


def test_rule_drift_and_shadow_detection() -> None:
    probe = RuleDriftAndSecretProbe()

    rule_text = """
    - 运行 npm test 验证构建
    - 检查 文件 src/legacy_controller.py 中的实现
    - 执行 pytest tests/
    """
    workspace_files = ["src/main.py", "tests/test_main.py", "pyproject.toml"]
    # Toolchain declares npm is disabled/replaced
    toolchain_manifest = {"npm": False, "pytest": True}

    report = probe.audit_rule_drift(
        rule_file_path="AGENTS.md",
        content=rule_text,
        workspace_files=workspace_files,
        toolchain_manifest=toolchain_manifest,
    )

    assert report.drift_count >= 2
    reasons = [item.drift_reason for item in report.drift_items if item.drift_reason]
    assert any("Claimed tool 'npm'" in r for r in reasons)
    assert any("legacy_controller.py" in r for r in reasons)

    # Shadowed rule detection
    shadow = probe.detect_shadowed_rules(
        directory_path="/workspace",
        found_rule_files=["SOUL.md", "AGENTS.md"],
    )
    assert shadow is not None
    assert shadow.dominant_file == "SOUL.md"
    assert "AGENTS.md" in shadow.shadowed_files
    assert "已被遮蔽未载入" in shadow.warning_notice


def test_persistent_rule_governance_suite_facade() -> None:
    suite = PersistentContextRuleDriftAuditAndExceptionAwareGovernanceSuite()

    raw_rule = """
    - 严禁未经确认重启服务【例外】：系统后台健康看门狗执行自动恢复除外
    - Deploy key: ghp_999988887777666655554444333322221111
    """

    safe_text, notices = suite.prepare_governed_rule_text(
        raw_content=raw_rule,
        directory_path="/workspace",
        sibling_files=["SOUL.md", "AGENTS.md"],
    )

    assert "ghp_" not in safe_text
    assert "[REDACTED_CREDENTIAL:" in safe_text
    assert len(notices) >= 2
    assert any("载入域保密越界" in n for n in notices)
    assert any("同目录下存在多规则文件遮蔽" in n for n in notices)

    # End to end evaluation
    clauses = suite.parse_rules(safe_text)
    assert len(clauses) >= 1
    wd_caller = RuleCallerContext(initiator="watchdog", is_system_watchdog=True)
    permitted, _ = suite.evaluate_action(clauses[0], wd_caller, "restart on crash")
    assert permitted is True
