# [INPUT]: ConflictArbitrationResult, DriftAuditReport, ExceptionAwareRuleParser, MemoryFileConflictArbiter, ParsedRuleClause, RuleCallerContext, RuleDriftAndSecretProbe, RuleGovernanceConfig, RuleSecretScanResult, ShadowedRuleFinding
# [OUTPUT]: PersistentContextRuleDriftAuditAndExceptionAwareGovernanceSuite
# [POS]: agent/workspace_rules/rule_governance/persistent_rule_governance_suite.py

"""End-to-end facade orchestrating persistent context rule drift auditing and exception-aware governance.

[INPUT]
- Domain models: ParsedRuleClause, RuleCallerContext, ConflictArbitrationResult, DriftAuditReport, RuleSecretScanResult, ShadowedRuleFinding.
- Component engines: ExceptionAwareRuleParser, MemoryFileConflictArbiter, RuleDriftAndSecretProbe.
- RuleGovernanceConfig: Tunable configuration.

[OUTPUT]
- PersistentContextRuleDriftAuditAndExceptionAwareGovernanceSuite: Unified facade.

[POS]
Top-level entry point in agent/workspace_rules/rule_governance establishing comprehensive AGENTS.md governance.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .exception_aware_rule_parser import ExceptionAwareRuleParser
from .governance_types import (
    ConflictArbitrationResult,
    DriftAuditReport,
    ParsedRuleClause,
    RuleCallerContext,
    RuleGovernanceConfig,
    RuleSecretScanResult,
    ShadowedRuleFinding,
)
from .memory_file_conflict_arbiter import MemoryFileConflictArbiter
from .rule_drift_and_secret_probe import RuleDriftAndSecretProbe


class PersistentContextRuleDriftAuditAndExceptionAwareGovernanceSuite:
    """Unified governance facade managing rule exceptions, SSOT memory conflict arbitration, and drift auditing."""

    def __init__(
        self,
        config: RuleGovernanceConfig | None = None,
        parser: ExceptionAwareRuleParser | None = None,
        arbiter: MemoryFileConflictArbiter | None = None,
        probe: RuleDriftAndSecretProbe | None = None,
    ) -> None:
        self._config = config or RuleGovernanceConfig()
        self._parser = parser or ExceptionAwareRuleParser()
        self._arbiter = arbiter or MemoryFileConflictArbiter(self._config)
        self._probe = probe or RuleDriftAndSecretProbe(self._config)

    @property
    def config(self) -> RuleGovernanceConfig:
        return self._config

    def parse_rules(self, content: str) -> Sequence[ParsedRuleClause]:
        """Parses raw rule markdown into structured clauses with core directives and explicit exceptions."""
        return self._parser.parse_document(content)

    def evaluate_action(
        self,
        clause: ParsedRuleClause,
        caller: RuleCallerContext,
        action_description: str,
    ) -> tuple[bool, str]:
        """Evaluates whether an action initiated by caller is permitted under the clause."""
        return self._parser.evaluate_action_permitted(clause, caller, action_description)

    def sanitize_content_secrets(self, content: str) -> RuleSecretScanResult:
        """Sanitizes sensitive tokens/credentials before rule text enters LLM prompts."""
        return self._probe.sanitize_secrets_in_content(content)

    def arbitrate_memory_file_conflict(
        self,
        memory_key: str,
        memory_fact: str,
        memory_mtime: float,
        rule_file_path: str,
        rule_content: str,
        file_mtime: float,
    ) -> ConflictArbitrationResult:
        """Arbitrates collisions between long-term memory facts and authoritative workspace rule files."""
        return self._arbiter.arbitrate_conflict(
            memory_key=memory_key,
            memory_fact=memory_fact,
            memory_mtime=memory_mtime,
            rule_file_path=rule_file_path,
            rule_content=rule_content,
            file_mtime=file_mtime,
        )

    def run_drift_audit(
        self,
        rule_file_path: str,
        content: str,
        workspace_files: Sequence[str] | set[str],
        toolchain_manifest: Mapping[str, bool] | None = None,
    ) -> DriftAuditReport:
        """Audits rule claims against actual workspace file tree and declared toolchains."""
        return self._probe.audit_rule_drift(
            rule_file_path=rule_file_path,
            content=content,
            workspace_files=workspace_files,
            toolchain_manifest=toolchain_manifest,
        )

    def audit_shadowed_rules(
        self,
        directory_path: str,
        found_rule_files: Sequence[str],
    ) -> ShadowedRuleFinding | None:
        """Identifies eclipsed sibling rule files in directory to prevent silent dropping."""
        return self._probe.detect_shadowed_rules(directory_path, found_rule_files)

    def prepare_governed_rule_text(
        self,
        raw_content: str,
        directory_path: str = "",
        sibling_files: Sequence[str] | None = None,
    ) -> tuple[str, Sequence[str]]:
        """Prepares sanitized rule prompt text and collects applicable warning banners."""
        notices: list[str] = []

        # 1. Sanitize secrets
        scan_res = self.sanitize_content_secrets(raw_content)
        sanitized_text = scan_res.redacted_content
        if scan_res.alert_banner:
            notices.append(scan_res.alert_banner)

        # 2. Check shadowed siblings
        if sibling_files and len(sibling_files) > 1:
            shadow_finding = self.audit_shadowed_rules(directory_path, sibling_files)
            if shadow_finding:
                notices.append(shadow_finding.warning_notice)

        return sanitized_text, tuple(notices)
