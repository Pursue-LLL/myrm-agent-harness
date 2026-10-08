"""Protector engine preserving last-round assistant tables and atomically compacting older tables.

[INPUT]
- table: MarkdownTableBlock extracted table block
- mode: TableProtectionMode pruning strategy

[OUTPUT]
- TablePruningProtector: Logic applying table preservation, well-formed folding, and atomic row truncation.

[POS]
Protector engine preserving last-round assistant tables and atomically compacting older tables.
"""

from __future__ import annotations

from typing import List, Optional

from .table_protection_types import MarkdownTableBlock, TableProtectionMode


class TablePruningProtector:
    """Safeguards last-round tables and formats historical tables into syntax-valid compacted representations."""

    @classmethod
    def compact_table_with_valid_syntax(
        cls,
        table: MarkdownTableBlock,
        max_rows_to_keep: int = 3,
    ) -> str:
        """Fold bulky historical table into a syntax-valid closed Markdown table with a summary row."""
        if table.row_count <= max_rows_to_keep:
            return table.raw_markdown

        headers = table.headers
        num_cols = len(headers)

        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join(["---"] * num_cols) + " |"

        kept_rows = table.rows[: max_rows_to_keep - 1]
        last_row = table.rows[-1]
        folded_count = table.row_count - max_rows_to_keep

        folded_cells = [f"... ({folded_count} rows omitted for brevity) ..."] + ["..."] * (num_cols - 1)
        folded_row_line = "| " + " | ".join(folded_cells[:num_cols]) + " |"

        rendered_lines: List[str] = [header_line, sep_line]
        for r in kept_rows:
            padded_row = r + [""] * (num_cols - len(r))
            rendered_lines.append("| " + " | ".join(padded_row[:num_cols]) + " |")

        rendered_lines.append(folded_row_line)
        padded_last = last_row + [""] * (num_cols - len(last_row))
        rendered_lines.append("| " + " | ".join(padded_last[:num_cols]) + " |")

        return "\n".join(rendered_lines)

    @classmethod
    def apply_table_protection(
        cls,
        text: str,
        table: MarkdownTableBlock,
        mode: TableProtectionMode,
    ) -> str:
        """Apply selected protection mode on the target table within message text."""
        if mode == TableProtectionMode.PRESERVE_ENTIRE_TABLE:
            return text

        if mode == TableProtectionMode.SEMANTIC_COMPACT_DIGEST:
            compacted = cls.compact_table_with_valid_syntax(table)
            return text[: table.start_char_index] + compacted + text[table.end_char_index :]

        if mode == TableProtectionMode.SAFE_ATOMIC_TRUNCATE:
            # Atomic truncate keeping only 2 rows and closing table cleanly
            truncated = cls.compact_table_with_valid_syntax(table, max_rows_to_keep=2)
            return text[: table.start_char_index] + truncated + text[table.end_char_index :]

        return text
