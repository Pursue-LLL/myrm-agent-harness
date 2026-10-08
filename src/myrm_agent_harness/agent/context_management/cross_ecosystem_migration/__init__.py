"""Cross-ecosystem agent rule migration and compatibility inspector package."""

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
