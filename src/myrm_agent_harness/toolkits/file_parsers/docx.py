"""Word document parser

Uses python-docx for parsing DOCX files with support for:
- Heading level preservation
- List item formatting (bullet and numbered)
- Table extraction with Markdown output and merged cell deduplication
- Document-order interleaving of paragraphs, lists, and tables

[INPUT]
- (none)

[OUTPUT]
- DocxParser: Word document parser using python-docx

[POS]
Word document parser
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)


class DocxParser(FileParser):
    """Word document parser using python-docx

    Extracts paragraphs and tables in document order, preserving heading
    levels and rendering tables as Markdown.
    """

    async def parse(self, file_path: str) -> str:
        """Parse Word document"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = await asyncio.to_thread(self._parse_sync, file_path)

        logger.warning("Word document parsed: %s, length: %d chars", path.name, len(content))
        return content

    def _parse_sync(self, file_path: str) -> str:
        """Synchronously parse Word document in element order."""
        try:
            from docx import Document
            from docx.oxml.ns import qn
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError as e:
            raise ImportError("python-docx is not installed. Run: uv add python-docx") from e

        doc = Document(file_path)
        blocks: list[str] = []

        for element in doc.element.body:
            tag = element.tag
            if tag == qn("w:p"):
                para = Paragraph(element, doc)
                text = para.text.strip()
                if not text:
                    continue
                style_name = para.style.name if para.style and para.style.name else ""
                if style_name.startswith("Heading"):
                    level_str = style_name.replace("Heading", "").strip()
                    try:
                        heading_level = int(level_str)
                        blocks.append(f"{'#' * heading_level} {text}")
                    except ValueError:
                        blocks.append(text)
                elif "List Bullet" in style_name:
                    blocks.append(f"- {text}")
                elif "List Number" in style_name:
                    blocks.append(f"1. {text}")
                else:
                    blocks.append(text)
            elif tag == qn("w:tbl"):
                table = Table(element, doc)
                md = self._table_to_markdown(table)
                if md:
                    blocks.append(md)

        return "\n\n".join(blocks)

    @staticmethod
    def _table_to_markdown(table: object) -> str:
        """Convert a python-docx Table to Markdown format."""
        rows: list[list[str]] = []
        for row in table.rows:  # type: ignore[attr-defined]
            cells: list[str] = []
            seen_tc: set[int] = set()
            for cell in row.cells:  # type: ignore[attr-defined]
                tc_id = id(cell._tc)  # type: ignore[attr-defined]
                if tc_id in seen_tc:
                    cells.append("")
                else:
                    seen_tc.add(tc_id)
                    text = cell.text.replace("|", "\\|").replace("\n", " ").strip()
                    cells.append(text)
            rows.append(cells)

        if not rows:
            return ""

        headers = rows[0]
        lines: list[str] = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for row in rows[1:]:
            while len(row) < len(headers):
                row.append("")
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    @property
    def supported_extensions(self) -> list[str]:
        return [".docx", ".doc"]
