"""Detector and parser identifying markdown tables in message text.

[INPUT]
- text: str message content potentially containing markdown tables

[OUTPUT]
- MarkdownTableDetector: Class offering regex and line-based table boundary detection and parsing.

[POS]
Detector and parser identifying markdown tables in message text.
"""

from __future__ import annotations

import re
from typing import List, Optional
import uuid

from .table_protection_types import MarkdownTableBlock


class MarkdownTableDetector:
    """Detects, parses, and validates GitHub-flavored Markdown tables within text bodies."""

    @classmethod
    def _is_table_separator_line(cls, line: str) -> bool:
        """Check if line matches markdown table header-separator syntax like |---|---|."""
        stripped = line.strip()
        if "|" not in stripped or "-" not in stripped:
            return False
        cells = [c.strip() for c in stripped.split("|")]
        if stripped.startswith("|") and cells and cells[0] == "":
            cells = cells[1:]
        if stripped.endswith("|") and cells and cells[-1] == "":
            cells = cells[:-1]
        if not cells:
            return False
        for c in cells:
            if not c or not re.match(r"^:?-+:?$", c):
                return False
        return True

    @classmethod
    def _parse_row_cells(cls, line: str) -> List[str]:
        """Split a markdown table row by pipes and strip cellular whitespace."""
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [cell.strip() for cell in stripped.split("|")]

    @classmethod
    def detect_tables(cls, text: str) -> List[MarkdownTableBlock]:
        """Scan text and return structured representation of all detected markdown tables."""
        if not text or "|" not in text:
            return []

        lines = text.split("\n")
        tables: List[MarkdownTableBlock] = []

        i = 0
        current_char_offset = 0
        line_offsets: List[int] = []
        for line in lines:
            line_offsets.append(current_char_offset)
            current_char_offset += len(line) + 1  # account for newline

        while i < len(lines) - 1:
            header_line = lines[i]
            sep_line = lines[i + 1]

            if "|" in header_line and cls._is_table_separator_line(sep_line):
                # We found a potential table starting at line i
                start_char_idx = line_offsets[i]
                headers = cls._parse_row_cells(header_line)
                data_rows: List[List[str]] = []
                table_lines: List[str] = [header_line, sep_line]

                j = i + 2
                while j < len(lines):
                    row_line = lines[j]
                    stripped = row_line.strip()
                    if stripped.startswith("|") or (stripped.endswith("|") and "|" in stripped):
                        cells = cls._parse_row_cells(row_line)
                        data_rows.append(cells)
                        table_lines.append(row_line)
                        j += 1
                    else:
                        break

                raw_md = "\n".join(table_lines)
                end_char_idx = start_char_idx + len(raw_md)

                block = MarkdownTableBlock(
                    table_id=f"tbl_{uuid.uuid4().hex[:8]}",
                    start_char_index=start_char_idx,
                    end_char_index=end_char_idx,
                    raw_markdown=raw_md,
                    headers=headers,
                    rows=data_rows,
                    row_count=len(data_rows),
                    column_count=len(headers),
                    is_well_formed=len(headers) > 0 and len(data_rows) >= 0,
                )
                tables.append(block)
                i = j
            else:
                i += 1

        return tables
