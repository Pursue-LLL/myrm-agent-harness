"""Tests for ExcelParser structure and audit modes

Validates the new output_format modes: "structure" (JSON metadata) and "audit"
(formula error detection), plus dynamic data_only switching.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.file_parsers.excel import ExcelParser


@pytest.fixture
def sample_xlsx(tmp_path: Path) -> str:
    """Create a minimal .xlsx with formulas and data for testing."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws["A1"] = "Product"
    ws["B1"] = "Revenue"
    ws["C1"] = "Tax"
    ws["A2"] = "Widget"
    ws["B2"] = 1000
    ws["C2"] = "=B2*0.1"
    ws["A3"] = "Gadget"
    ws["B3"] = 2000
    ws["C3"] = "=B3*0.1"

    ws2 = wb.create_sheet("Summary")
    ws2["A1"] = "Total Revenue"
    ws2["B1"] = "=Sales!B2+Sales!B3"

    path = tmp_path / "test.xlsx"
    wb.save(str(path))
    return str(path)


@pytest.fixture
def broken_ref_xlsx(tmp_path: Path) -> str:
    """Create .xlsx with a broken sheet reference for audit testing."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws["A1"] = "Value"
    ws["A2"] = 100
    ws["B1"] = "Ref"
    ws["B2"] = "='DeletedSheet'!A1"

    path = tmp_path / "broken.xlsx"
    wb.save(str(path))
    return str(path)


class TestExcelParserMarkdown:
    """Existing markdown mode still works correctly."""

    @pytest.mark.asyncio
    async def test_default_format_is_markdown(self, sample_xlsx: str) -> None:
        parser = ExcelParser()
        result = await parser.parse(sample_xlsx)
        assert "## Sheet: Sales" in result
        assert "| Product | Revenue | Tax |" in result

    @pytest.mark.asyncio
    async def test_text_format(self, sample_xlsx: str) -> None:
        parser = ExcelParser(output_format="text")
        result = await parser.parse(sample_xlsx)
        assert "## Sheet: Sales" in result
        assert "|" not in result.split("\n")[1] or "---" not in result


class TestExcelParserStructure:
    """Structure mode returns lightweight JSON metadata."""

    @pytest.mark.asyncio
    async def test_returns_valid_json(self, sample_xlsx: str) -> None:
        parser = ExcelParser(output_format="structure")
        result = await parser.parse(sample_xlsx)
        data = json.loads(result)
        assert "sheets" in data

    @pytest.mark.asyncio
    async def test_contains_sheet_metadata(self, sample_xlsx: str) -> None:
        parser = ExcelParser(output_format="structure")
        result = await parser.parse(sample_xlsx)
        data = json.loads(result)

        sheets = data["sheets"]
        assert len(sheets) == 2

        sales = sheets[0]
        assert sales["name"] == "Sales"
        assert sales["rows"] == 3
        assert sales["cols"] == 3
        assert "Product" in sales["headers"]
        assert "Revenue" in sales["headers"]

    @pytest.mark.asyncio
    async def test_detects_formulas(self, sample_xlsx: str) -> None:
        parser = ExcelParser(output_format="structure")
        result = await parser.parse(sample_xlsx)
        data = json.loads(result)

        sales = data["sheets"][0]
        assert "formula_columns" in sales
        assert "C" in sales["formula_columns"]
        assert sales["formula_count"] == 2

    @pytest.mark.asyncio
    async def test_detects_cross_sheet_refs(self, sample_xlsx: str) -> None:
        parser = ExcelParser(output_format="structure")
        result = await parser.parse(sample_xlsx)
        data = json.loads(result)

        summary = data["sheets"][1]
        assert "cross_references" in summary
        assert "Sales" in summary["cross_references"]
        assert "cross_sheet_references" in data

    @pytest.mark.asyncio
    async def test_output_is_compact_for_large_files(self, tmp_path: Path) -> None:
        """Structure mode output should be much smaller than content mode for large files."""
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "BigData"
        ws.append(["ID", "Name", "Value", "Category", "Date"])
        for i in range(200):
            ws.append([i, f"Item_{i}", i * 10.5, f"Cat_{i % 5}", "2024-01-01"])
        path = tmp_path / "large.xlsx"
        wb.save(str(path))

        parser_content = ExcelParser(output_format="markdown")
        parser_structure = ExcelParser(output_format="structure")

        content = await parser_content.parse(str(path))
        structure = await parser_structure.parse(str(path))

        assert len(structure) < len(content) * 0.1


class TestExcelParserAudit:
    """Audit mode detects formula issues."""

    @pytest.mark.asyncio
    async def test_returns_valid_json(self, sample_xlsx: str) -> None:
        parser = ExcelParser(output_format="audit")
        result = await parser.parse(sample_xlsx)
        data = json.loads(result)
        assert "findings" in data
        assert "summary" in data

    @pytest.mark.asyncio
    async def test_clean_file_no_errors(self, sample_xlsx: str) -> None:
        parser = ExcelParser(output_format="audit")
        result = await parser.parse(sample_xlsx)
        data = json.loads(result)
        assert data["summary"]["errors"] == 0

    @pytest.mark.asyncio
    async def test_detects_broken_reference(self, broken_ref_xlsx: str) -> None:
        parser = ExcelParser(output_format="audit")
        result = await parser.parse(broken_ref_xlsx)
        data = json.loads(result)

        assert data["summary"]["errors"] >= 1
        finding = data["findings"][0]
        assert finding["category"] == "broken_reference"
        assert "DeletedSheet" in finding["description"]
        assert finding["sheet"] == "Data"


class TestExcelParserDataOnly:
    """data_only switches correctly based on mode."""

    @pytest.mark.asyncio
    async def test_content_mode_returns_values(self, sample_xlsx: str) -> None:
        """In content mode (data_only=True), formulas show as calculated values or empty."""
        parser = ExcelParser(output_format="markdown")
        result = await parser.parse(sample_xlsx)
        assert "=B2*0.1" not in result

    @pytest.mark.asyncio
    async def test_structure_mode_reads_formulas(self, sample_xlsx: str) -> None:
        """In structure mode (data_only=False), formulas are preserved."""
        parser = ExcelParser(output_format="structure")
        result = await parser.parse(sample_xlsx)
        data = json.loads(result)
        assert data["sheets"][0]["formula_count"] == 2


class TestExcelParserEdgeCases:
    """Edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        parser = ExcelParser(output_format="structure")
        with pytest.raises(FileNotFoundError):
            await parser.parse("/nonexistent/file.xlsx")

    @pytest.mark.asyncio
    async def test_empty_workbook(self, tmp_path: Path) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Empty"
        path = tmp_path / "empty.xlsx"
        wb.save(str(path))

        parser = ExcelParser(output_format="structure")
        result = await parser.parse(str(path))
        data = json.loads(result)
        assert data["sheets"][0]["name"] == "Empty"

    @pytest.mark.asyncio
    async def test_supported_extensions(self) -> None:
        parser = ExcelParser()
        assert ".xlsx" in parser.supported_extensions
        assert ".xls" in parser.supported_extensions
