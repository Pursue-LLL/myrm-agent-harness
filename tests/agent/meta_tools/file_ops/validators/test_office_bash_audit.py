"""Tests for Office bash post-audit."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from openpyxl import Workbook

from myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit import (
    OfficeBashAudit,
)


def _write_xlsx_with_formula(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet["A1"] = 1
    sheet["A2"] = "=SUM(A1:A1)"
    workbook.save(path)


def _write_xlsx_without_formula(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet["A1"] = 1
    sheet["A2"] = 2
    workbook.save(path)


@pytest.mark.asyncio
async def test_finalize_audit_warns_when_formulas_removed(tmp_path: Path) -> None:
    workbook_path = tmp_path / "report.xlsx"
    _write_xlsx_with_formula(workbook_path)
    command = f"python edit {workbook_path}"
    snapshots = OfficeBashAudit.prepare_snapshots(str(tmp_path), command)
    _write_xlsx_without_formula(workbook_path)

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit.run_layout_qa_check",
        new=AsyncMock(return_value=[]),
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit.run_xlsx_recalc_check",
        new=AsyncMock(return_value=[]),
    ):
        warnings = await OfficeBashAudit.finalize_audit(
            snapshots,
            str(tmp_path),
            command,
            None,
        )

    assert any("formula" in warning.lower() for warning in warnings)


@pytest.mark.asyncio
async def test_finalize_audit_no_metric_warnings_on_unchanged_xlsx(tmp_path: Path) -> None:
    workbook_path = tmp_path / "report.xlsx"
    _write_xlsx_with_formula(workbook_path)
    command = f"python noop {workbook_path}"
    snapshots = OfficeBashAudit.prepare_snapshots(str(tmp_path), command)

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit.run_layout_qa_check",
        new=AsyncMock(return_value=[]),
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit.run_xlsx_recalc_check",
        new=AsyncMock(return_value=[]),
    ):
        warnings = await OfficeBashAudit.finalize_audit(
            snapshots,
            str(tmp_path),
            command,
            None,
        )

    assert warnings == []


@pytest.mark.asyncio
async def test_finalize_audit_warns_when_generated_file_missing_baseline(
    tmp_path: Path,
) -> None:
    workbook_path = tmp_path / "report.xlsx"
    _write_xlsx_with_formula(workbook_path)
    command = "python script.py"

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit.run_layout_qa_check",
        new=AsyncMock(return_value=[]),
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit.run_xlsx_recalc_check",
        new=AsyncMock(return_value=[]),
    ):
        warnings = await OfficeBashAudit.finalize_audit(
            {},
            str(tmp_path),
            command,
            [str(workbook_path)],
        )

    assert any("not verified" in warning.lower() for warning in warnings)


@pytest.mark.asyncio
async def test_finalize_audit_warns_on_corrupt_docx(tmp_path: Path) -> None:
    docx_path = tmp_path / "contract.docx"
    docx_path.write_bytes(b"not-a-valid-docx")
    command = f"python edit {docx_path}"

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit.run_layout_qa_check",
        new=AsyncMock(return_value=[]),
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit.run_xlsx_recalc_check",
        new=AsyncMock(return_value=[]),
    ):
        warnings = await OfficeBashAudit.finalize_audit(
            {},
            str(tmp_path),
            command,
            None,
        )

    assert any("corrupt" in warning.lower() for warning in warnings)
    assert any(docx_path.name in warning for warning in warnings)
