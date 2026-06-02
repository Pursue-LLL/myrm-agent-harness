"""Excel file parser

Uses openpyxl for parsing XLSX files with support for:
- Merged cells handling
- Markdown table output
- Multiple worksheets

[INPUT]
- (none)

[OUTPUT]
- ExcelParser: Excel file parser using openpyxl

[POS]
Excel file parser
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

if TYPE_CHECKING:
    from openpyxl.worksheet.worksheet import Worksheet

logger = logging.getLogger(__name__)


class ExcelParser(FileParser):
    """Excel file parser using openpyxl

    Features:
    - Merged cells handling (auto-flatten)
    - Markdown table output format
    - Multiple worksheets
    """

    def __init__(self, output_format: str = "markdown"):
        self._output_format = output_format

    async def parse(self, file_path: str) -> str:
        """Parse Excel file"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = await asyncio.to_thread(self._parse_sync, file_path)

        logger.warning("Excel file parsed: %s, length: %d chars", path.name, len(content))
        return content

    def _parse_sync(self, file_path: str) -> str:
        """Synchronously parse Excel file"""
        try:
            from openpyxl import load_workbook
        except ImportError as e:
            raise ImportError("openpyxl is not installed. Run: uv add openpyxl") from e

        wb = load_workbook(file_path, data_only=True)
        all_text: list[str] = []

        for sheet_name in wb.sheetnames:
            sheet: Worksheet = wb[sheet_name]
            data = self._build_data_matrix(sheet)
            if not data:
                continue

            if self._output_format == "markdown":
                sheet_text = self._format_markdown_table(sheet_name, data)
            else:
                sheet_text = self._format_text_table(sheet_name, data)

            all_text.append(sheet_text)

        return "\n\n".join(all_text)

    def _build_data_matrix(self, sheet: Worksheet) -> list[list[str]]:
        """Build data matrix with merged cells handling"""
        max_row = sheet.max_row or 0
        max_col = sheet.max_column or 0
        if max_row == 0 or max_col == 0:
            return []

        data: list[list[str]] = [["" for _ in range(max_col)] for _ in range(max_row)]

        for row_idx, row in enumerate(sheet.iter_rows(values_only=True)):
            for col_idx, cell in enumerate(row):
                if cell is not None:
                    data[row_idx][col_idx] = str(cell)

        for merged_range in sheet.merged_cells.ranges:
            top_left_cell = sheet.cell(merged_range.min_row, merged_range.min_col)
            value = str(top_left_cell.value) if top_left_cell.value is not None else ""

            for row in range(merged_range.min_row, merged_range.max_row + 1):
                for col in range(merged_range.min_col, merged_range.max_col + 1):
                    data[row - 1][col - 1] = value

        return [row for row in data if any(cell.strip() for cell in row)]

    def _format_markdown_table(self, sheet_name: str, data: list[list[str]]) -> str:
        """Format as Markdown table"""
        if not data:
            return f"## Sheet: {sheet_name}\n\n*Empty*"

        lines = [f"## Sheet: {sheet_name}", ""]

        headers = [self._escape_markdown_cell(cell) for cell in data[0]]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for row in data[1:]:
            cells = [self._escape_markdown_cell(cell) for cell in row]
            while len(cells) < len(headers):
                cells.append("")
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)

    def _format_text_table(self, sheet_name: str, data: list[list[str]]) -> str:
        """Format as plain text (pipe-separated)"""
        lines = [f"## Sheet: {sheet_name}"]
        for row in data:
            lines.append(" | ".join(row))
        return "\n".join(lines)

    @staticmethod
    def _escape_markdown_cell(text: str) -> str:
        """Escape Markdown table cell"""
        if not text:
            return ""
        return text.replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()

    @property
    def supported_extensions(self) -> list[str]:
        return [".xlsx", ".xls"]
