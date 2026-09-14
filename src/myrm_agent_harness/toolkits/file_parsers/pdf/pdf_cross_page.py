"""Cross-page table stitching with precision-first guards.

[INPUT]
- tables: PDFTable fragments in page/reading order
- page_heights: {page_number: page height}

[OUTPUT]
- stitch_cross_page_tables: merged table list; merged tables carry page_range

[POS]
Post-extraction helper. Only merges boundary fragments with strong evidence
(repeated header, or matching column signature plus a cut-row cue); everything
else is left untouched so unrelated tables are never corrupted.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from myrm_agent_harness.toolkits.file_parsers.base import PDFTable

logger = logging.getLogger(__name__)

BOTTOM_MARGIN_PT = 48.0
TOP_MARGIN_PT = 108.0
# Near-full-page boxes are layout artifacts (two-column grids, slide frames),
# while a genuine middle fragment of a long stitched table can still cover
# most of its page, hence the high cut-off.
MAX_TABLE_HEIGHT_RATIO = 0.95
COLUMN_X_TOLERANCE_PT = 6.0
MIN_MERGE_ROWS = 2


def stitch_cross_page_tables(
    tables: Sequence[PDFTable],
    page_heights: Mapping[int, float],
) -> list[PDFTable]:
    """Merge table fragments that continue across page boundaries."""
    if not tables:
        return list(tables)

    stitched: list[PDFTable] = []
    for table in tables:
        if stitched and _can_merge(stitched[-1], table, page_heights):
            _merge_into(stitched[-1], table)
            continue
        stitched.append(table)

    merged_count = len(tables) - len(stitched)
    if merged_count:
        logger.info("Cross-page table stitching merged %d fragment(s)", merged_count)
    return stitched


def _can_merge(
    previous: PDFTable,
    current: PDFTable,
    page_heights: Mapping[int, float],
) -> bool:
    """Decide whether two fragments are one logical table split by a page break."""
    if previous.bbox is None or current.bbox is None:
        return False

    last_page = previous.page_range[1] if previous.page_range else previous.page_number
    if current.page_number != last_page + 1:
        return False

    last_height = page_heights.get(last_page)
    current_height = page_heights.get(current.page_number)
    if not last_height or not current_height:
        return False

    previous_height = previous.bbox[3] - previous.bbox[1]
    current_fragment_height = current.bbox[3] - current.bbox[1]
    if previous_height <= 0 or current_fragment_height <= 0:
        return False
    if previous_height > last_height * MAX_TABLE_HEIGHT_RATIO:
        return False
    if current_fragment_height > current_height * MAX_TABLE_HEIGHT_RATIO:
        return False
    if last_height - previous.bbox[3] > BOTTOM_MARGIN_PT:
        return False
    if current.bbox[1] > TOP_MARGIN_PT:
        return False

    if len(previous.data) < MIN_MERGE_ROWS or not current.data:
        return False

    previous_columns = _column_count(previous)
    if previous_columns < 2 or previous_columns != _column_count(current):
        return False

    if _headers_equal(previous, current):
        return True
    return _column_signature_matches(previous, current) and _has_cut_row_cue(previous)


def _merge_into(previous: PDFTable, current: PDFTable) -> None:
    """Append the continuation fragment, dropping a repeated header row."""
    if _headers_equal(previous, current):
        previous.data = previous.data + current.data[1:]
    else:
        previous.data = previous.data + current.data

    # Keep the last fragment's geometry so chain merges keep evaluating the
    # correct page height and boundary proximity.
    previous.bbox = current.bbox
    first_page = previous.page_range[0] if previous.page_range else previous.page_number
    previous.page_range = (first_page, current.page_range[1] if current.page_range else current.page_number)


def _headers_equal(previous: PDFTable, current: PDFTable) -> bool:
    if not previous.data or not current.data:
        return False
    previous_header = _normalize_row(previous.data[0])
    current_header = _normalize_row(current.data[0])
    if not any(previous_header) or not any(current_header):
        return False
    return previous_header == current_header


def _normalize_row(row: Sequence[str]) -> list[str]:
    return [str(cell).strip() for cell in row]


def _column_count(table: PDFTable) -> int:
    return max((len(row) for row in table.data), default=0)


def _column_signature_matches(previous: PDFTable, current: PDFTable) -> bool:
    previous_columns = previous.column_starts
    current_columns = current.column_starts
    if not previous_columns or not current_columns:
        return False
    if len(previous_columns) != len(current_columns):
        return False
    return all(
        abs(left - right) <= COLUMN_X_TOLERANCE_PT
        for left, right in zip(previous_columns, current_columns, strict=True)
    )


def _has_cut_row_cue(table: PDFTable) -> bool:
    """A last row whose later cells are empty indicates a page-break cut."""
    if len(table.data) < 2:
        return False
    last_row = table.data[-1]
    if len(last_row) < 2 or not last_row[0].strip():
        return False
    return any(not str(cell).strip() for cell in last_row[1:])
