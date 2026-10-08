# [INPUT]: None
# [OUTPUT]: ConflictArbitrationResult, DriftAuditReport, DriftInspectionTarget, ParsedRuleClause, RuleCallerContext, RuleGovernanceConfig, RuleSecretScanResult, ShadowedRuleFinding
# [POS]: agent/workspace_rules/rule_governance/governance_types.py

"""Domain models and contracts for persistent context rule drift auditing and exception-aware governance.

[INPUT]
- None (Self-contained domain dataclasses and config).

[OUTPUT]
- RuleCallerContext: Context describing the action initiator (system watchdog, human user, background cron).
- ParsedRuleClause: Decomposed rule line with core directive and explicit exception branches.
- DriftInspectionTarget: Individual claim/command/path extracted from rules evaluated against repository state.
- DriftAuditReport: Aggregate findings of rule drift audit including stale commands and deleted paths.
- ConflictArbitrationResult: Arbitration outcome resolving memory vs. workspace rule file collisions.
- RuleSecretScanResult: Findings from pre-flight secret and PII confidentiality scanning over rule text.
- ShadowedRuleFinding: Detection record of eclipsed sibling rule files in identical directories.
- RuleGovernanceConfig: Tunables and threshold settings for rule governance.

[POS]
Domain model layer for AGENTS.md / workspace rule lifecycle governance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class RuleCallerContext:
    """Attributes characterizing who is performing an action under governed rules."""

    initiator: str
    is_system_watchdog: bool = False
    action_type: str = "execution"
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedRuleClause:
    """Individual rule statement split into imperative requirement and explicit exception conditions."""

    rule_id: str
    raw_text: str
    core_directive: str
    exceptions: Sequence[str] = field(default_factory=list)
    is_strict: bool = False


@dataclass(frozen=True)
class DriftInspectionTarget:
    """Extracted assertion from rules checking existence of referenced commands or filesystem paths."""

    rule_text: str
    claimed_command: str | None = None
    claimed_path: str | None = None
    evidence_found: bool = True
    drift_reason: str | None = None


@dataclass(frozen=True)
class DriftAuditReport:
    """Consolidated report produced during low-peak rule drift inspection."""

    scanned_files: Sequence[str]
    drift_count: int
    drift_items: Sequence[DriftInspectionTarget]
    timestamp: float


@dataclass(frozen=True)
class ConflictArbitrationResult:
    """Outcome when long-term memory facts disagree with authoritative workspace rule files."""

    memory_key: str
    rule_file_path: str
    file_mtime: float
    memory_mtime: float
    winner: str  # "file" | "memory"
    arbitration_reason: str
    alert_message: str


@dataclass(frozen=True)
class RuleSecretScanResult:
    """Results from scanning rule text for credentials or PII before prompt injection."""

    has_violation: bool
    redacted_content: str
    detected_token_kinds: Sequence[str]
    alert_banner: str | None = None


@dataclass(frozen=True)
class ShadowedRuleFinding:
    """Audit of overshadowed rule files within the same directory due to first-match precedence."""

    directory_path: str
    dominant_file: str
    shadowed_files: Sequence[str]
    warning_notice: str


@dataclass(frozen=True)
class RuleGovernanceConfig:
    """Thresholds and flags governing rule auditing and exceptions."""

    enable_secret_redaction: bool = True
    enable_shadow_audit: bool = True
    file_ssot_authoritative: bool = True
    max_drift_scan_items: int = 50
