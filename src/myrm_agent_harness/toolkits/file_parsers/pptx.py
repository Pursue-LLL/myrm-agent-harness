"""PowerPoint document parser

Uses python-pptx for parsing PPTX files with support for:
- Slide text extraction (titles, body, text boxes)
- Table extraction with Markdown output
- Speaker notes extraction

[INPUT]
- (none)

[OUTPUT]
- PptxParser: PowerPoint document parser using python-pptx

[POS]
PowerPoint document parser
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)


class PptxParser(FileParser):
    """PowerPoint document parser using python-pptx

    Extracts slide text, tables, and speaker notes into Markdown format.
    Each slide becomes a section with heading and content.
    """

    async def parse(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = await asyncio.to_thread(self._parse_sync, file_path)

        logger.warning("PowerPoint parsed: %s, length: %d chars", path.name, len(content))
        return content

    def _parse_sync(self, file_path: str) -> str:
        try:
            from pptx import Presentation
        except ImportError as e:
            raise ImportError("python-pptx is not installed. Run: uv add python-pptx") from e

        prs = Presentation(file_path)
        slides_output: list[str] = []

        for slide_idx, slide in enumerate(prs.slides, start=1):
            slide_parts: list[str] = [f"## Slide {slide_idx}"]

            text_parts: list[str] = []
            table_parts: list[str] = []

            for shape in slide.shapes:
                if shape.has_table:
                    table_parts.append(self._extract_table(shape.table))
                elif shape.has_text_frame:
                    for paragraph in shape.text_frame.paragraphs:
                        text = paragraph.text.strip()
                        if text:
                            text_parts.append(text)

            if text_parts:
                slide_parts.append("\n".join(text_parts))

            if table_parts:
                slide_parts.extend(table_parts)

            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
                if notes_text:
                    slide_parts.append(f"\n> **Notes:** {notes_text}")

            if len(slide_parts) > 1:
                slides_output.append("\n\n".join(slide_parts))

        return "\n\n---\n\n".join(slides_output) if slides_output else "(Empty presentation)"

    @staticmethod
    def _extract_table(table: object) -> str:
        """Extract table as Markdown."""
        rows: list[list[str]] = []
        for row in table.rows:  # type: ignore[attr-defined]
            cells: list[str] = []
            for cell in row.cells:
                text = cell.text.replace("|", "\\|").replace("\n", " ").strip()
                cells.append(text)
            rows.append(cells)

        if not rows:
            return ""

        lines: list[str] = []
        headers = rows[0]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows[1:]:
            while len(row) < len(headers):
                row.append("")
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    @property
    def supported_extensions(self) -> list[str]:
        return [".pptx", ".ppt"]
