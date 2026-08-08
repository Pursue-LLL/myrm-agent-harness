"""CSV file parser."""

from __future__ import annotations

import csv
import logging
from io import StringIO
from pathlib import Path

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)


class CsvParser(FileParser):
    """Parse CSV into markdown table text."""

    async def parse(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        raw = path.read_text(encoding="utf-8")
        reader = csv.reader(StringIO(raw))
        rows = [row for row in reader if any(cell.strip() for cell in row)]
        if not rows:
            return ""

        header = rows[0]
        body = rows[1:] if len(rows) > 1 else []
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * len(header)) + " |",
        ]
        for row in body:
            padded = row + [""] * max(0, len(header) - len(row))
            lines.append("| " + " | ".join(padded[: len(header)]) + " |")

        logger.warning("CSV parsed: %s, rows=%d", path.name, len(rows))
        return "\n".join(lines)

    @property
    def supported_extensions(self) -> list[str]:
        return [".csv"]
