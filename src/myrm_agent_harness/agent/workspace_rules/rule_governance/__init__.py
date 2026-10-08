"""Public contracts and facade for persistent context rule governance, exception evaluation, and drift auditing.

[INPUT]
- None (Facade exports).

[OUTPUT]
- ConflictArbitrationResult: Conflict adjudication result between memory and workspace files.
- DriftAuditReport: Report of stale commands and deleted path references in rules.
- DriftInspectionTarget: Single drift inspection item.
- ExceptionAwareRuleParser: Parser for core directives and explicit exception branches.
- MemoryFileConflictArbiter: Arbiter establishing workspace files as SSOT.
- ParsedRuleClause: Decomposed rule clause representation.
- PersistentContextRuleDriftAuditAndExceptionAwareGovernanceSuite: End-to-end governance facade.
- RuleCallerContext: Context describing action initiators.
- RuleDriftAndSecretProbe: Active probe checking drift, secret leaks, and shadowed files.
- RuleGovernanceConfig: Tunable configuration.
- RuleSecretScanResult: Result from pre-flight secret redaction.
- ShadowedRuleFinding: Detection record for eclipsed sibling rules.

[POS]
Modular subpackage in agent/workspace_rules implementing Markus (@googelhupf42) inspired rule governance.
"""

from __future__ import annotations

from .exception_aware_rule_parser import ExceptionAwareRuleParser
from .governance_types import (
    ConflictArbitrationResult,
    DriftAuditReport,
    DriftInspectionTarget,
    ParsedRuleClause,
    RuleCallerContext,
    RuleGovernanceConfig,
    RuleSecretScanResult,
    ShadowedRuleFinding,
)
from .memory_file_conflict_arbiter import MemoryFileConflictArbiter
from .persistent_rule_governance_suite import (
    PersistentContextRuleDriftAuditAndExceptionAwareGovernanceSuite,
)
from .rule_drift_and_secret_probe import RuleDriftAndSecretProbe

__all__ = [
    "ConflictArbitrationResult",
    "DriftAuditReport",
    "DriftInspectionTarget",
    "ExceptionAwareRuleParser",
    "MemoryFileConflictArbiter",
    "ParsedRuleClause",
    "PersistentContextRuleDriftAuditAndExceptionAwareGovernanceSuite",
    "RuleCallerContext",
    "RuleDriftAndSecretProbe",
    "RuleGovernanceConfig",
    "RuleSecretScanResult",
    "ShadowedRuleFinding",
]
