# [INPUT] FileDriftAuditResult, PersonaFileKind, PurificationExecutionResult, ReconciliationDiffPlan from .drift_types, LineByLineRealityReconciler, PurificationDiffEngine
# [OUTPUT] DeterministicPersonaMemoryDriftAuditSuite, DeterministicPersonaMemoryDriftAuditAndLineByLineReconciliationSuite
# [POS] Unified facade suite orchestrating workspace persona file auditing, diff plan construction, and confirmed purification

"""Unified facade suite for deterministic persona memory drift audit and reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from .drift_types import (
    FileDriftAuditResult,
    PersonaFileKind,
    PurificationExecutionResult,
    ReconciliationDiffPlan,
)
from .line_by_line_reconciler import LineByLineRealityReconciler
from .purification_diff_engine import PurificationDiffEngine

CANONICAL_PERSONA_FILE_SPECS: list[tuple[str, PersonaFileKind]] = [
    ("SOUL.md", "SOUL"),
    ("soul.md", "SOUL"),
    ("USER.md", "USER"),
    ("user.md", "USER"),
    ("MEMORY.md", "MEMORY"),
    ("memory.md", "MEMORY"),
    ("AGENTS.md", "AGENTS"),
    ("agents.md", "AGENTS"),
]


class DeterministicPersonaMemoryDriftAuditSuite:
    """Unified facade orchestrating line-by-line reality checks and human-gated memory purification."""

    @classmethod
    def audit_file_content(
        cls,
        file_path: str,
        content: str,
        file_kind: PersonaFileKind = "UNKNOWN",
        workspace_root: Path | None = None,
    ) -> FileDriftAuditResult:
        """Audit the given file content line-by-line against reality."""
        return LineByLineRealityReconciler.audit_persona_file(
            file_path=file_path,
            content=content,
            file_kind=file_kind,
            workspace_root=workspace_root,
        )

    @classmethod
    def audit_workspace(cls, workspace_dir: Path | str) -> list[FileDriftAuditResult]:
        """Scan workspace root and audit all recognized SOUL, USER, MEMORY, and AGENTS files."""
        ws_path = Path(workspace_dir)
        results: list[FileDriftAuditResult] = []
        if not ws_path.exists() or not ws_path.is_dir():
            return []

        disk_entries = {p.name: p for p in ws_path.iterdir() if p.is_file()}
        visited_real_paths: set[Path] = set()

        for filename, kind in CANONICAL_PERSONA_FILE_SPECS:
            if filename in disk_entries:
                candidate = disk_entries[filename]
                real_p = candidate.resolve()
                if real_p in visited_real_paths:
                    continue
                visited_real_paths.add(real_p)
                content = candidate.read_text(encoding="utf-8")
                audit_res = cls.audit_file_content(
                    file_path=str(candidate),
                    content=content,
                    file_kind=kind,
                    workspace_root=ws_path,
                )
                results.append(audit_res)

        return results

    @classmethod
    def generate_diff_plans(
        cls,
        audit_results: list[FileDriftAuditResult],
    ) -> list[ReconciliationDiffPlan]:
        """Generate strictly read-only diff plans for all audited files with flagged flaws."""
        plans: list[ReconciliationDiffPlan] = []
        for res in audit_results:
            if not res.has_flaws:
                continue
            path = Path(res.file_path)
            content = path.read_text(encoding="utf-8") if path.exists() else ""
            plan = PurificationDiffEngine.generate_diff_plan(res, content)
            plans.append(plan)
        return plans

    @classmethod
    def apply_plan(
        cls,
        plan: ReconciliationDiffPlan,
        user_confirmed: bool,
    ) -> PurificationExecutionResult:
        """Apply a reconciliation plan enforcing the 'Read only until my yes' gate."""
        return PurificationDiffEngine.apply_purification(
            diff_plan=plan,
            user_confirmed=user_confirmed,
            create_backup=True,
        )


# Canonical alias for roadmap naming compliance
DeterministicPersonaMemoryDriftAuditAndLineByLineReconciliationSuite = (
    DeterministicPersonaMemoryDriftAuditSuite
)
