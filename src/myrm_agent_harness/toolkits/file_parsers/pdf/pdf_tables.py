"""PDF table extraction, rendering and stitching finalization.

[INPUT]
- pdfplumber page objects and PDFTable fragments
- Table extraction settings (line strategy + tolerances)

[OUTPUT]
- extract_page_tables: line-based + heuristic borderless table fragments
- clean_table_data: cell cleanup helper
- finalize_tables: stable IDs plus rendered Markdown/L0 summaries
- format_table_markdown / generate_table_summary_l0: rendering helpers

[POS]
Table domain of the PDF parser: per-page extraction with column anchors for
cross-page stitching, and final Markdown/L0 rendering after stitching.
"""

from __future__ import annotations

import logging
import re
import typing
from collections import defaultdict

from myrm_agent_harness.toolkits.file_parsers.base import PDFTable

if typing.TYPE_CHECKING:
    import pdfplumber.page

logger = logging.getLogger(__name__)

DEFAULT_TABLE_SETTINGS: dict[str, str | int] = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "intersection_tolerance": 3,
    "snap_tolerance": 3,
    "join_tolerance": 3,
}


def extract_page_tables(
    page: pdfplumber.page.Page,
    table_settings: dict[str, str | int] | None = None,
) -> list[PDFTable]:
    """Extract tables from a page (line-based first, heuristic forms second)."""
    settings = table_settings or DEFAULT_TABLE_SETTINGS
    tables: list[PDFTable] = []
    table_bboxes: list[tuple[float, float, float, float]] = []

    try:
        # Primary extraction: Explicit line-based table extraction
        raw_tables = page.find_tables(settings)

        for idx, raw_table in enumerate(raw_tables):
            table_data = raw_table.extract()
            if not table_data or not any(table_data):
                continue

            cleaned = clean_table_data(table_data)
            if cleaned:
                tables.append(
                    PDFTable(
                        page_number=0,
                        table_index=idx,
                        data=cleaned,
                        bbox=raw_table.bbox,
                        column_starts=_column_starts(raw_table),
                    )
                )
                table_bboxes.append(raw_table.bbox)

        # Secondary extraction: Heuristic form/borderless table extraction (Lazy Trigger)
        page_text = page.extract_text() or ""

        # Lazy Trigger: Only trigger if there are multiple wide spaces indicating columnar alignment,
        # or if the page is extremely sparse (like a scanned invoice with few chars)
        trigger_heuristic = False
        # Check for multiple instances of 3+ spaces (including Tab and NBSP) which often indicate aligned columns
        if len(re.findall(r"[ \t\xa0]{3,}", page_text)) >= 3:
            trigger_heuristic = True
        elif len(page.chars) < 2000 and len(table_bboxes) == 0:
            # Sparse page without explicit tables, might be a borderless form
            trigger_heuristic = True

        if trigger_heuristic:
            # Memory-Dict Collision Masking: extract words once and filter in pure Python
            all_words = page.extract_words(keep_blank_chars=False, x_tolerance=3, y_tolerance=3)

            remaining_words = []
            for w in all_words:
                w_x0, w_y0, w_x1, w_y1 = w["x0"], w["top"], w["x1"], w["bottom"]
                in_any_bbox = False
                for bx0, by0, bx1, by1 in table_bboxes:
                    # Check intersection
                    if not (w_x1 < bx0 or w_x0 > bx1 or w_y1 < by0 or w_y0 > by1):
                        in_any_bbox = True
                        break
                if not in_any_bbox:
                    remaining_words.append(w)

            if remaining_words:
                from .pdf_heuristic_table import extract_heuristic_tables_from_words

                page_width = page.width if hasattr(page, "width") else 612.0
                heuristic_tables = extract_heuristic_tables_from_words(remaining_words, float(page_width))

                # Merge heuristic table results
                base_idx = len(tables)
                for h_idx, (h_data, h_bbox) in enumerate(heuristic_tables):
                    tables.append(
                        PDFTable(
                            page_number=0,
                            table_index=base_idx + h_idx,
                            data=h_data,
                            bbox=h_bbox,
                        )
                    )

        # Sort all tables by their vertical position (y0) to ensure correct reading order
        tables.sort(key=lambda t: t.bbox[1] if t.bbox else 0)

        # Reassign indices after sorting
        for idx, table in enumerate(tables):
            table.table_index = idx

    except Exception as e:
        logger.warning("Table extraction failed: %s", e)

    return tables


def finalize_tables(tables: list[PDFTable]) -> None:
    """Assign stable IDs and render Markdown/L0 summaries after stitching."""
    tables_by_page: dict[int, list[PDFTable]] = defaultdict(list)
    for table in tables:
        tables_by_page[table.page_number].append(table)

    for page_tables in tables_by_page.values():
        for idx, table in enumerate(page_tables):
            table.table_index = idx
            table.id = f"table_{table.page_number}_{idx}"
            table.markdown = format_table_markdown(table)
            table.summary_l0 = generate_table_summary_l0(table)


def clean_table_data(raw_table: list[list[str | None]]) -> list[list[str]]:
    """Clean table data: convert None to empty string, remove empty rows"""
    cleaned: list[list[str]] = []

    for row in raw_table:
        cleaned_row = [str(cell).strip() if cell else "" for cell in row]
        if any(cell for cell in cleaned_row):
            cleaned.append(cleaned_row)

    return cleaned


def format_table_markdown(table: PDFTable) -> str:
    """Format table as Markdown"""
    if not table.data or len(table.data) < 2:
        return f"**Table {table.table_index + 1}** (empty)"

    location = f"Pages {table.page_range[0]}–{table.page_range[1]}" if table.page_range else f"Page {table.page_number}"

    lines: list[str] = [
        f"**Table {table.table_index + 1}** ({location})",
        "",
    ]

    headers = [cell.replace("|", "\\|") for cell in table.data[0]]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in table.data[1:]:
        cells = [cell.replace("|", "\\|") for cell in row]
        while len(cells) < len(headers):
            cells.append("")
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


def generate_table_summary_l0(table: PDFTable) -> str:
    """Generates a heuristic L0 summary for the table capsule.

    Focuses on structural information for semantic indexing.
    """
    if not table.data:
        return "Empty table"

    header = table.data[0]
    row_count = len(table.data) - 1
    cols_summary = ", ".join([str(c) for c in header[:5]])
    if len(header) > 5:
        cols_summary += "..."

    location = f"Pages {table.page_range[0]}-{table.page_range[1]}" if table.page_range else f"Page {table.page_number}"
    summary = f"Structured Table on {location}. Rows: {row_count}. Headers: [{cols_summary}]. "

    # Add a glimpse of the first data row if available for better semantic matching
    if row_count > 0:
        first_row = table.data[1]
        row_preview = ", ".join([str(c) for c in first_row[:3]])
        summary += f"Data sample: {row_preview}."

    return summary.strip()


def _column_starts(raw_table: typing.Any) -> tuple[float, ...] | None:
    """Column x anchors from the first multi-cell row (stitching evidence)."""
    try:
        for row in raw_table.rows:
            cells = getattr(row, "cells", None)
            if not cells:
                continue
            starts = [round(float(cell[0]), 1) for cell in cells if cell]
            if len(starts) >= 2:
                return tuple(starts)
    except Exception:
        return None
    return None
