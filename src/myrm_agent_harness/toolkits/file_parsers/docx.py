"""Word document parser

Uses python-docx for parsing DOCX files with support for:
- Heading level preservation
- List item formatting (bullet and numbered)
- Table extraction with Markdown output and merged cell deduplication
- Document-order interleaving of paragraphs, lists, and tables
- Structure mode: JSON metadata with paragraph IDs, styles, table structures for incremental edits

[INPUT]
- (none)

[OUTPUT]
- DocxParser: Word document parser using python-docx

[POS]
Word document parser
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Literal

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)

DocxOutputFormat = Literal["markdown", "structure"]


class DocxParser(FileParser):
    """Word document parser using python-docx

    Extracts paragraphs and tables in document order, preserving heading
    levels and rendering tables as Markdown.
    Structure mode outputs JSON metadata with paragraph IDs, styles, and table
    structures for enabling precise incremental edits.
    """

    def __init__(self, output_format: DocxOutputFormat = "markdown"):
        self._output_format: DocxOutputFormat = output_format

    async def parse(self, file_path: str) -> str:
        """Parse Word document"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = await asyncio.to_thread(self._parse_sync, file_path)

        logger.info("Word document parsed: %s, format=%s, length: %d chars", path.name, self._output_format, len(content))
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

        if self._output_format == "structure":
            return self._build_structure(doc, qn, Paragraph, Table)

        return self._build_markdown(doc, qn, Paragraph, Table)

    def _build_markdown(
        self,
        doc: object,
        qn: object,
        Paragraph: type,
        Table: type,
    ) -> str:
        """Build Markdown content from document."""
        blocks: list[str] = []

        for element in doc.element.body:  # type: ignore[attr-defined]
            tag = element.tag
            if tag == qn("w:p"):  # type: ignore[operator]
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
            elif tag == qn("w:tbl"):  # type: ignore[operator]
                table = Table(element, doc)
                md = self._table_to_markdown(table)
                if md:
                    blocks.append(md)

        return "\n\n".join(blocks)

    def _build_structure(
        self,
        doc: object,
        qn: object,
        Paragraph: type,
        Table: type,
    ) -> str:
        """Return JSON structural metadata for the document."""
        elements: list[dict[str, object]] = []
        element_idx = 0

        for element in doc.element.body:  # type: ignore[attr-defined]
            tag = element.tag
            if tag == qn("w:p"):  # type: ignore[operator]
                para = Paragraph(element, doc)
                para_id = element.get(
                    "{http://schemas.microsoft.com/office/word/2010/wordml}paraId"
                )
                if para_id is None:
                    para_id = f"_idx_{element_idx}"

                text = para.text.strip()
                style_name = para.style.name if para.style and para.style.name else "Normal"

                has_images = bool(element.findall(f".//{qn('w:drawing')}"))  # type: ignore[operator, arg-type]

                para_info: dict[str, object] = {
                    "type": "paragraph",
                    "index": element_idx,
                    "para_id": para_id,
                    "style": style_name,
                    "text_preview": text[:200] if text else "",
                }
                if has_images:
                    para_info["has_images"] = True
                elements.append(para_info)

            elif tag == qn("w:tbl"):  # type: ignore[operator]
                table = Table(element, doc)
                rows_data: list[list[str]] = []
                for row in table.rows:
                    cells: list[str] = []
                    seen_tc: set[int] = set()
                    for cell in row.cells:
                        tc_id = id(cell._tc)
                        if tc_id in seen_tc:
                            cells.append("")
                        else:
                            seen_tc.add(tc_id)
                            cells.append(cell.text.strip()[:100])
                    rows_data.append(cells)

                tbl_info: dict[str, object] = {
                    "type": "table",
                    "index": element_idx,
                    "rows": len(rows_data),
                    "cols": len(rows_data[0]) if rows_data else 0,
                }
                if rows_data:
                    tbl_info["header_cells"] = rows_data[0][:10]
                elements.append(tbl_info)

            element_idx += 1

        doc_meta = self._extract_doc_metadata(doc)

        result: dict[str, object] = {
            "element_count": len(elements),
            **doc_meta,
            "elements": elements,
        }
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _extract_doc_metadata(doc: object) -> dict[str, object]:
        """Extract document-level metadata (title, author, sections)."""
        meta: dict[str, object] = {}
        core = getattr(doc, "core_properties", None)
        if core:
            if core.title:
                meta["title"] = core.title
            if core.author:
                meta["author"] = core.author

        sections = getattr(doc, "sections", None)
        if sections:
            meta["section_count"] = len(sections)

        return meta

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
