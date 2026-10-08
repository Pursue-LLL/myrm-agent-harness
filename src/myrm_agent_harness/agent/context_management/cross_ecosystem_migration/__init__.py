"""Cross-ecosystem agent rule migration and compatibility inspector package.

[INPUT]
- agent.context_management.cross_ecosystem_migration.cross_ecosystem_scanner::CrossEcosystemRuleScanner (POS:
  Scanner discovering foreign and standard agent rule files across ecosystems.)
-
  agent.context_management.cross_ecosystem_migration.cross_ecosystem_suite::CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite
  (POS: Suite inspecting workspace multi-ecosystem rules, detecting conflicts, and transpiling to AGENTS.md.)
- agent.context_management.cross_ecosystem_migration.cross_ecosystem_transpiler::CrossEcosystemTranspiler
  (POS: Transpiler detecting conflicts and consolidating multi-ecosystem rule files into AGENTS.md.)
- agent.context_management.cross_ecosystem_migration.cross_ecosystem_types::DiscoveredEcosystemFile,
  EcosystemConflictItem, EcosystemSpecKind, RuleMigrationReportReceipt, RuleSectionCategory (POS: Types for
  cross-ecosystem agent rule migration and compatibility inspector.)

[OUTPUT]
- Re-exports: CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite, CrossEcosystemRuleScanner,
  CrossEcosystemTranspiler, DiscoveredEcosystemFile, EcosystemConflictItem, EcosystemSpecKind,
  RuleMigrationReportReceipt, RuleSectionCategory

[POS]
Cross-ecosystem agent rule migration and compatibility inspector package.
"""

from __future__ import annotations

from .cross_ecosystem_scanner import CrossEcosystemRuleScanner
from .cross_ecosystem_suite import (
    CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite,
)
from .cross_ecosystem_transpiler import CrossEcosystemTranspiler
from .cross_ecosystem_types import (
    DiscoveredEcosystemFile,
    EcosystemConflictItem,
    EcosystemSpecKind,
    RuleMigrationReportReceipt,
    RuleSectionCategory,
)

__all__ = [
    "CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite",
    "CrossEcosystemRuleScanner",
    "CrossEcosystemTranspiler",
    "DiscoveredEcosystemFile",
    "EcosystemConflictItem",
    "EcosystemSpecKind",
    "RuleMigrationReportReceipt",
    "RuleSectionCategory",
]
