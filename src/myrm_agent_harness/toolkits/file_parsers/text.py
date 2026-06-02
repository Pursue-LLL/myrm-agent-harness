"""Text file parser

Supports plain text and Markdown files.

[INPUT]
- (none)

[OUTPUT]
- TextParser: Plain text/Markdown parser

[POS]
Text file parser
"""

from __future__ import annotations

import logging
from pathlib import Path

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)


class TextParser(FileParser):
    """Plain text/Markdown parser"""

    async def parse(self, file_path: str) -> str:
        """Parse text file"""
        import aiofiles

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        async with aiofiles.open(file_path, encoding="utf-8") as f:
            content = await f.read()

        logger.warning("Text file parsed: %s, length: %d chars", path.name, len(content))
        return content

    @property
    def supported_extensions(self) -> list[str]:
        return [".txt", ".md", ".markdown", ".rst", ".text"]
