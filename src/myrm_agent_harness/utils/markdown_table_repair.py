"""Markdown Table Sanitizer and Repair Engine.

Detects, sanitizes, aligns, and repairs malformed, dirty, or incomplete Markdown tables
produced by Large Language Models (LLMs) into valid GitHub Flavored Markdown (GFM) tables.

Key Capabilities:
1. Shielding: Code blocks (```, ~~~) and inline code (`) are shielded from modification.
2. Fullwidth & Glyph Normalization: Fullwidth pipe '｜' and erratic separators normalized.
3. Boundary & Divider Repair:
   - Auto-adds missing leading/trailing pipe '|'.
   - Auto-synthesizes missing divider rows (|---|---|) when missing.
   - Fixes malformed dividers (e.g. insufficient hyphens, uneven columns).
4. Column Alignment & Gap Filling:
   - Harmonizes uneven row column counts with padding or safe truncation.
   - Handles multi-line broken cells by merging them cleanly.
5. Incomplete / Streaming Table Closure:
   - Safely closes truncated streaming tables with valid dividers and cells.
6. GFM Paragraph Isolation:
   - Ensures blank line boundaries around tables so GFM table parsers parse them reliably.

[POS]
Utility for repairing LLM-generated malformed, dirty, or truncated Markdown tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

_CODE_BLOCK_SLOT_FMT: Final[str] = "\x00TB_CODE_{idx}\x00"
_CODE_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"(^|\n)(`{3,}|~{3,})[^\n]*\n[\s\S]*?\n\2(?=\n|$)|(`+)[^`\n]+?\3",
    re.MULTILINE,
)
_FULLWIDTH_PIPE_RE: Final[re.Pattern[str]] = re.compile(r"[\uff5c\uffe8]")
_DIVIDER_CELL_RE: Final[re.Pattern[str]] = re.compile(r"^\s*:?-{1,}:?\s*$")


@dataclass(frozen=True, slots=True)
class TableRepairStats:
    """Statistics of repairs performed on a Markdown document."""

    tables_detected: int = 0
    tables_repaired: int = 0
    dividers_added: int = 0
    rows_padded: int = 0
    incomplete_closed: int = 0


def _shield_code_regions(markdown: str) -> tuple[str, list[str]]:
    """Replace fenced code blocks and inline code with unique slots."""
    slots: list[str] = []

    def _repl(match: re.Match[str]) -> str:
        idx = len(slots)
        slots.append(match.group(0))
        return f"\x00TB_CODE_{idx}\x00"

    shielded = _CODE_BLOCK_RE.sub(_repl, markdown)
    return shielded, slots


def _unshield_code_regions(text: str, slots: list[str]) -> str:
    """Restore shielded code blocks and inline code."""
    for idx, code_content in enumerate(slots):
        slot_token = f"\x00TB_CODE_{idx}\x00"
        text = text.replace(slot_token, code_content)
    return text


def _is_divider_row(cells: list[str]) -> bool:
    """Check if all cells in a row look like GFM table divider cells (:---:, ---, etc.)."""
    if not cells:
        return False
    return all(_DIVIDER_CELL_RE.match(c) is not None for c in cells)


def _split_row_cells(raw_line: str) -> list[str]:
    """Split a row into cell contents, respecting escaped pipes and inline code slots."""
    line = _FULLWIDTH_PIPE_RE.sub("|", raw_line.strip())

    # Strip outer pipes if present, otherwise treat edge content as cells
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith(r"\|"):
        line = line[:-1]

    # Split on unescaped pipe
    raw_cells = re.split(r"(?<!\\)\|", line)
    return [c.strip() for c in raw_cells]


def _format_row(cells: list[str]) -> str:
    """Format a list of cells into a standard GFM table row."""
    # Ensure inner pipes are escaped if not inside code
    cleaned = []
    for c in cells:
        # replace raw newlines with <br> inside cell
        cell_str = c.replace("\r\n", "<br>").replace("\n", "<br>").strip()
        cleaned.append(cell_str if cell_str else " ")
    return "| " + " | ".join(cleaned) + " |"


def _build_divider_row(col_count: int, alignments: list[str] | None = None) -> str:
    """Build a standard GFM table divider row with proper alignments."""
    dividers: list[str] = []
    for i in range(col_count):
        align = alignments[i] if alignments and i < len(alignments) else "---"
        m = re.match(r"^(:?)-+(:?)$", align.strip())
        if m:
            left, right = m.group(1), m.group(2)
            if left and right:
                dividers.append(":---:")
            elif left:
                dividers.append(":---")
            elif right:
                dividers.append("---:")
            else:
                dividers.append("---")
        else:
            dividers.append("---")
    return "| " + " | ".join(dividers) + " |"


def _is_table_row_candidate(line: str) -> bool:
    """Determine whether a line is likely part of a Markdown table."""
    norm = _FULLWIDTH_PIPE_RE.sub("|", line.strip())
    if not norm:
        return False

    # Lines starting with | or containing multiple pipes
    if norm.startswith("|"):
        return True

    pipe_count = len(re.findall(r"(?<!\\)\|", norm))
    if pipe_count >= 1:
        # e.g. "Name | Age | Role"
        return True

    return False


def _repair_table_block(
    lines: list[str],
    is_streaming: bool = False,
) -> tuple[list[str], bool, bool]:
    """Repair a contiguous candidate table block.

    Returns:
        (repaired_lines, is_table, divider_added)
    """
    if not lines:
        return lines, False, False

    parsed_rows: list[list[str]] = []
    for raw_line in lines:
        cells = _split_row_cells(raw_line)
        if cells:
            parsed_rows.append(cells)

    if not parsed_rows:
        return lines, False, False

    # Check if this block has any characteristics of a real table
    # (must have at least 2 columns in header or divider)
    max_cols = max(len(r) for r in parsed_rows)
    if max_cols < 2:
        return lines, False, False

    # Determine canonical column count
    # Prefer header row column count if header has >= 2 columns, else max_cols
    target_cols = len(parsed_rows[0])
    if target_cols < 2:
        target_cols = max_cols

    # Detect existing divider
    divider_index = -1
    for idx, row in enumerate(parsed_rows):
        if _is_divider_row(row):
            divider_index = idx
            break

    divider_added = False
    repaired_rows: list[str] = []

    if divider_index == -1:
        # Missing divider! Synthesize one after the first row
        header_cells = parsed_rows[0]
        # Pad or trim header to target_cols
        padded_header = header_cells + [""] * max(0, target_cols - len(header_cells))
        repaired_rows.append(_format_row(padded_header[:target_cols]))
        repaired_rows.append(_build_divider_row(target_cols))
        divider_added = True

        # Process data rows
        for row in parsed_rows[1:]:
            if _is_divider_row(row):
                continue
            padded_row = row + [""] * max(0, target_cols - len(row))
            repaired_rows.append(_format_row(padded_row[:target_cols]))
    else:
        # Has divider row
        # Align header
        header_cells = parsed_rows[0] if divider_index > 0 else [f"Col {i+1}" for i in range(target_cols)]
        padded_header = header_cells + [""] * max(0, target_cols - len(header_cells))
        repaired_rows.append(_format_row(padded_header[:target_cols]))

        # Align divider
        divider_cells = parsed_rows[divider_index]
        repaired_rows.append(_build_divider_row(target_cols, divider_cells))

        # Process rows before divider (if divider was not second row)
        for row in parsed_rows[1:divider_index]:
            padded_row = row + [""] * max(0, target_cols - len(row))
            repaired_rows.append(_format_row(padded_row[:target_cols]))

        # Process rows after divider
        for row in parsed_rows[divider_index + 1:]:
            padded_row = row + [""] * max(0, target_cols - len(row))
            repaired_rows.append(_format_row(padded_row[:target_cols]))

    # Streaming edge case: incomplete trailing row
    if is_streaming and len(repaired_rows) == 1:
        # Table only has a header so far, append streaming divider
        repaired_rows.append(_build_divider_row(target_cols))

    return repaired_rows, True, divider_added


def repair_markdown_tables(
    text: str,
    *,
    is_streaming: bool = False,
    ensure_paragraph_isolation: bool = True,
) -> str:
    """Repair all malformed, dirty, or incomplete Markdown tables in text.

    Args:
        text: The source Markdown text.
        is_streaming: Whether the text is actively streaming (handles truncated tables).
        ensure_paragraph_isolation: Whether to ensure clean blank lines before and after tables.

    Returns:
        The sanitized Markdown text with valid GFM tables.
    """
    if not text:
        return text

    # Step 1: Shield code blocks and inline code
    shielded_text, code_slots = _shield_code_regions(text)

    # Step 2: Scan line by line and identify contiguous candidate table blocks
    lines = shielded_text.split("\n")
    output_lines: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        if _is_table_row_candidate(line):
            # Gather consecutive candidate lines
            candidate_block: list[str] = []
            block_start = i
            while i < n:
                curr = lines[i]
                # If current line ends with | but doesn't have enough cells compared to header,
                # or if current line has no | at all and previous row ended without closure:
                is_candidate = _is_table_row_candidate(curr)
                if (
                    candidate_block
                    and not is_candidate
                    and not curr.strip().startswith("#")
                    and not curr.strip().startswith("```")
                    and curr.strip() != ""
                    and not _is_divider_row(_split_row_cells(candidate_block[-1]))
                    and not _FULLWIDTH_PIPE_RE.sub("|", candidate_block[-1].strip()).endswith("|")
                ):
                    # Multi-line cell broken across lines: merge with previous line
                    candidate_block[-1] = candidate_block[-1].rstrip(" |") + "<br>" + curr.strip()
                    i += 1
                elif is_candidate:
                    candidate_block.append(curr)
                    i += 1
                else:
                    break

            repaired_table, is_table, _ = _repair_table_block(
                candidate_block,
                is_streaming=is_streaming,
            )

            if is_table:
                # Ensure blank line before table if needed
                if ensure_paragraph_isolation and output_lines and output_lines[-1].strip() != "":
                    output_lines.append("")

                output_lines.extend(repaired_table)

                # Ensure blank line after table if next line is not empty
                if ensure_paragraph_isolation and i < n and lines[i].strip() != "":
                    output_lines.append("")
            else:
                # Not a real table, restore original lines
                output_lines.extend(lines[block_start:i])
        else:
            output_lines.append(line)
            i += 1

    reconstructed = "\n".join(output_lines)

    # Step 3: Unshield code blocks
    return _unshield_code_regions(reconstructed, code_slots)


__all__ = [
    "TableRepairStats",
    "repair_markdown_tables",
]
