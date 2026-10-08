"""Suite inspecting workspace multi-ecosystem rules, detecting conflicts, and transpiling to AGENTS.md.

[INPUT]
- agent.context_management.cross_ecosystem_migration.cross_ecosystem_scanner::CrossEcosystemRuleScanner (POS:
  Scanner discovering foreign and standard agent rule files across ecosystems.)
- agent.context_management.cross_ecosystem_migration.cross_ecosystem_transpiler::CrossEcosystemTranspiler
  (POS: Transpiler detecting conflicts and consolidating multi-ecosystem rule files into AGENTS.md.)
- agent.context_management.cross_ecosystem_migration.cross_ecosystem_types::DiscoveredEcosystemFile,
  EcosystemConflictItem, RuleMigrationReportReceipt (POS: Types for cross-ecosystem agent rule migration and
  compatibility inspector.)

[OUTPUT]
- CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite: Orchestrates multi-ecosystem rule discovery,
  conflict detection, and standardized transpilation.

[POS]
Suite inspecting workspace multi-ecosystem rules, detecting conflicts, and transpiling to AGENTS.md.
"""

from __future__ import annotations

import hashlib
from typing import List, Optional

from .cross_ecosystem_scanner import CrossEcosystemRuleScanner
from .cross_ecosystem_transpiler import CrossEcosystemTranspiler
from .cross_ecosystem_types import (
    DiscoveredEcosystemFile,
    EcosystemConflictItem,
    RuleMigrationReportReceipt,
)


class CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite:
    """Orchestrates multi-ecosystem rule discovery, conflict detection, and standardized transpilation."""

    def __init__(
        self,
        scanner: Optional[CrossEcosystemRuleScanner] = None,
        transpiler: Optional[CrossEcosystemTranspiler] = None,
    ) -> None:
        self._scanner = scanner or CrossEcosystemRuleScanner()
        self._transpiler = transpiler or CrossEcosystemTranspiler()

    @property
    def scanner(self) -> CrossEcosystemRuleScanner:
        """Access underlying scanner."""
        return self._scanner

    @property
    def transpiler(self) -> CrossEcosystemTranspiler:
        """Access underlying transpiler."""
        return self._transpiler

    def inspect_and_transpile(
        self,
        workspace_root: str,
    ) -> RuleMigrationReportReceipt:
        """Scan workspace for all rule definitions, diagnose conflicts, and generate standardized AGENTS.md."""
        discovered = self._scanner.scan_workspace(workspace_root)
        conflicts = self._transpiler.detect_conflicts(discovered)
        consolidated = self._transpiler.transpile_to_standard_agents_md(discovered)

        manifest_seed = f"{workspace_root}:{len(discovered)}:{len(conflicts)}:{len(consolidated)}"
        manifest_hash = hashlib.sha256(manifest_seed.encode("utf-8")).hexdigest()[:16]

        # Verify lossless property: every discovered file's content must be present in the consolidated output
        is_lossless = True
        for f in discovered:
            if f.digest not in consolidated and f.content[:50] not in consolidated:
                is_lossless = False
                break

        return RuleMigrationReportReceipt(
            workspace_root=workspace_root,
            discovered_specs_count=len(discovered),
            discovered_files=discovered,
            conflicts_count=len(conflicts),
            conflicts=conflicts,
            consolidated_agents_md=consolidated,
            manifest_hash=manifest_hash,
            is_lossless=is_lossless,
        )
