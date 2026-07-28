"""Unit tests for Office OPC utilities."""

from __future__ import annotations

import zipfile
from pathlib import Path

from openpyxl import Workbook

from myrm_agent_harness.agent.meta_tools.file_ops.utils.office_opc import (
    collect_docx_opc_metrics,
    collect_xlsx_formulas,
    compare_docx_opc_metrics,
    compare_xlsx_formulas,
    extract_office_paths_from_command,
    office_file_audit_read_error,
)
from myrm_agent_harness.agent.meta_tools.file_ops.utils.office_scope import (
    is_office_docx_path,
    is_office_xlsx_path,
)


def _write_minimal_docx(path: Path, *, run_properties: int = 0) -> None:
    rpr_blocks = "".join("<w:rPr/>" for _ in range(run_properties))
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r>{rpr_blocks}<w:t>Hello</w:t></w:r></w:p></w:body>
</w:document>""".encode()
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        zf.writestr("word/document.xml", document)


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


def test_office_scope_extensions() -> None:
    assert is_office_docx_path("/tmp/report.docx") is True
    assert is_office_xlsx_path("/tmp/data.xlsx") is True
    assert is_office_docx_path("/tmp/readme.md") is False


def test_extract_office_paths_from_command() -> None:
    command = 'python -c "open(\'/tmp/out.docx\', \'wb\')"'
    paths = extract_office_paths_from_command(command)
    assert "/tmp/out.docx" in paths


def test_collect_docx_opc_metrics(tmp_path: Path) -> None:
    docx = tmp_path / "sample.docx"
    _write_minimal_docx(docx, run_properties=4)
    metrics = collect_docx_opc_metrics(docx)
    assert metrics is not None
    assert metrics.run_properties_count == 4


def test_compare_docx_opc_metrics_warns_on_large_drop() -> None:
    from myrm_agent_harness.agent.meta_tools.file_ops.utils.office_opc import DocxOpcMetrics

    before = DocxOpcMetrics(run_properties_count=12)
    after = DocxOpcMetrics(run_properties_count=2)
    warnings = compare_docx_opc_metrics(before, after)
    assert len(warnings) == 1
    assert "formatting" in warnings[0].lower()


def test_compare_xlsx_formulas(tmp_path: Path) -> None:
    before_path = tmp_path / "before.xlsx"
    after_path = tmp_path / "after.xlsx"
    _write_xlsx_with_formula(before_path)
    _write_xlsx_without_formula(after_path)
    before = collect_xlsx_formulas(before_path)
    after = collect_xlsx_formulas(after_path)
    warnings = compare_xlsx_formulas(before, after)
    assert any("formula" in warning.lower() for warning in warnings)


def test_office_file_audit_read_error_warns_on_corrupt_docx(tmp_path: Path) -> None:
    corrupt_docx = tmp_path / "contract.docx"
    corrupt_docx.write_bytes(b"not-a-valid-docx")

    warning = office_file_audit_read_error(corrupt_docx)

    assert warning is not None
    assert "corrupt" in warning.lower()
    assert corrupt_docx.name in warning


def test_office_file_audit_read_error_warns_on_corrupt_xlsx(tmp_path: Path) -> None:
    corrupt_xlsx = tmp_path / "report.xlsx"
    corrupt_xlsx.write_bytes(b"not-a-valid-xlsx")

    warning = office_file_audit_read_error(corrupt_xlsx)

    assert warning is not None
    assert "corrupt" in warning.lower()
    assert corrupt_xlsx.name in warning


def test_office_file_audit_read_error_none_for_valid_docx(tmp_path: Path) -> None:
    docx = tmp_path / "sample.docx"
    _write_minimal_docx(docx)

    assert office_file_audit_read_error(docx) is None


def test_office_file_audit_read_error_skips_legacy_doc(tmp_path: Path) -> None:
    legacy_doc = tmp_path / "legacy.doc"
    legacy_doc.write_bytes(b"legacy-ole-bytes-not-zip")

    assert office_file_audit_read_error(legacy_doc) is None
