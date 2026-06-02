"""Word document parser

Uses python-docx for parsing DOCX files.

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
    """Word document parser using python-docx"""

    async def parse(self, file_path: str) -> str:
        """Parse Word document"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = await asyncio.to_thread(self._parse_sync, file_path)

        logger.warning("Word document parsed: %s, length: %d chars", path.name, len(content))
        return content

    def _parse_sync(self, file_path: str) -> str:
        """Synchronously parse Word document"""
        try:
            from docx import Document
        except ImportError as e:
            raise ImportError("python-docx is not installed. Run: uv add python-docx") from e

        doc = Document(file_path)
        paragraphs: list[str] = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            style_name = para.style.name if para.style and para.style.name else ""
            if style_name.startswith("Heading"):
                level_str = style_name.replace("Heading", "").strip()
                try:
                    heading_level = int(level_str)
                    paragraphs.append(f"{'#' * heading_level} {text}")
                except ValueError:
                    paragraphs.append(text)
            else:
                paragraphs.append(text)

        return "\n\n".join(paragraphs)

    @property
    def supported_extensions(self) -> list[str]:
        return [".docx", ".doc"]
