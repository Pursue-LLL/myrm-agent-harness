"""Post-bash Office write audit — formula and OPC fidelity checks.

[INPUT]
- workspace_root, command text, generated_files from bash executor
- utils.office_recalc::run_xlsx_recalc_check (POS: optional LibreOffice recalc error scan)
- observers.layout_qa_observer::run_layout_qa_check (POS: optional soffice PDF layout QA)

[OUTPUT]
- OfficeBashAudit.prepare_snapshots / finalize_audit (includes corrupt Office package read warn)

[POS]
Primary Office write-fidelity path (office-document skill uses bash_code_execute).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.agent.meta_tools.file_ops.observers.layout_qa_observer import (
    run_layout_qa_check,
)
from myrm_agent_harness.agent.meta_tools.file_ops.utils.office_opc import (
    DocxOpcMetrics,
    XlsxFormulaSnapshot,
    collect_docx_opc_metrics,
    collect_xlsx_formulas,
    compare_docx_opc_metrics,
    compare_xlsx_formulas,
    extract_office_paths_from_command,
    office_file_audit_read_error,
    resolve_office_path,
)
from myrm_agent_harness.agent.meta_tools.file_ops.utils.office_recalc import (
    run_xlsx_recalc_check,
)
from myrm_agent_harness.agent.meta_tools.file_ops.utils.office_scope import (
    is_office_docx_path,
    is_office_xlsx_path,
)


@dataclass(frozen=True)
class OfficeFileSnapshot:
    """Pre-execution metrics for one Office file."""

    path: Path
    docx_metrics: DocxOpcMetrics | None
    xlsx_formulas: XlsxFormulaSnapshot | None


class OfficeBashAudit:
    """Snapshot and compare Office files touched by bash/python execution."""

    @staticmethod
    def collect_candidate_paths(
        workspace_root: str,
        command: str,
        generated_files: list[str] | None,
    ) -> list[Path]:
        """Merge command-mentioned paths with executor-reported generated files."""
        candidates: list[Path] = []
        seen: set[str] = set()

        for raw in extract_office_paths_from_command(command):
            resolved = resolve_office_path(workspace_root, raw)
            key = str(resolved)
            if key not in seen:
                seen.add(key)
                candidates.append(resolved)

        for raw in generated_files or []:
            resolved = resolve_office_path(workspace_root, raw)
            if not (is_office_docx_path(str(resolved)) or is_office_xlsx_path(str(resolved))):
                continue
            key = str(resolved)
            if key not in seen:
                seen.add(key)
                candidates.append(resolved)

        return candidates

    @staticmethod
    def snapshot_file(path: Path) -> OfficeFileSnapshot | None:
        """Capture pre-edit metrics when the file already exists."""
        if not path.is_file():
            return None
        docx_metrics = collect_docx_opc_metrics(path) if is_office_docx_path(str(path)) else None
        xlsx_formulas = collect_xlsx_formulas(path) if is_office_xlsx_path(str(path)) else None
        if docx_metrics is None and xlsx_formulas is None:
            return None
        return OfficeFileSnapshot(path=path, docx_metrics=docx_metrics, xlsx_formulas=xlsx_formulas)

    @staticmethod
    def prepare_snapshots(
        workspace_root: str,
        command: str,
    ) -> dict[str, OfficeFileSnapshot]:
        """Snapshot existing Office files referenced by the command before execution."""
        snapshots: dict[str, OfficeFileSnapshot] = {}
        for path in OfficeBashAudit.collect_candidate_paths(workspace_root, command, None):
            snap = OfficeBashAudit.snapshot_file(path)
            if snap is not None:
                snapshots[str(path)] = snap
        return snapshots

    @staticmethod
    async def finalize_audit(
        snapshots: dict[str, OfficeFileSnapshot],
        workspace_root: str,
        command: str,
        generated_files: list[str] | None,
    ) -> list[str]:
        """Compare post-execution files against snapshots and return warnings."""
        warnings: list[str] = []
        paths = OfficeBashAudit.collect_candidate_paths(workspace_root, command, generated_files)
        command_path_keys = {
            str(item)
            for item in OfficeBashAudit.collect_candidate_paths(workspace_root, command, None)
        }

        for path in paths:
            key = str(path)
            before = snapshots.get(key)

            if not path.is_file():
                continue

            read_error = office_file_audit_read_error(path)
            if read_error is not None:
                warnings.append(read_error)
                continue

            after_docx = collect_docx_opc_metrics(path) if is_office_docx_path(str(path)) else None
            after_xlsx = collect_xlsx_formulas(path) if is_office_xlsx_path(str(path)) else None

            if before is not None:
                warnings.extend(compare_docx_opc_metrics(before.docx_metrics, after_docx))
                warnings.extend(compare_xlsx_formulas(before.xlsx_formulas, after_xlsx))
            elif key not in command_path_keys:
                warnings.append(
                    f"Office fidelity was not verified for {path.name}: "
                    "no pre-execution baseline was captured. "
                    "Include the file path in the bash command for automatic audit."
                )

            if is_office_docx_path(str(path)):
                warnings.extend(await run_layout_qa_check(path))

            if (
                is_office_xlsx_path(str(path))
                and after_xlsx is not None
                and after_xlsx.formulas
            ):
                warnings.extend(await run_xlsx_recalc_check(path))

        return warnings
