"""Heuristic PDF Table Extractor

Implements an advanced spatial coordinate clustering algorithm to extract 
borderless forms and hidden-grid tables from PDF pages.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pdfplumber.page

logger = logging.getLogger(__name__)

# Pattern for MasterFormat-style partial numbering (e.g., ".1", ".2", ".10")
PARTIAL_NUMBERING_PATTERN = re.compile(r"^\.\d+$")


def extract_heuristic_tables_from_words(
    words: list[dict[str, Any]],
    page_width: float = 612.0,
) -> list[tuple[list[list[str]], tuple[float, float, float, float]]]:
    """
    Extract form-style and borderless tables by analyzing word spatial positions.
    Returns a list of tables, each represented as a tuple of (data_matrix, bbox).
    bbox format: (x0, y0, x1, y1)
    """
    if not words:
        return []

    # Dynamic scaling for tolerance based on page width (assuming 612 as standard letter width)
    dynamic_col_tolerance = max(15.0, page_width * 0.065)

    # Group words by their Y position (rows) using a 5-point tolerance
    y_tolerance = 5
    rows_by_y: dict[float, list[dict[str, Any]]] = {}
    for word in words:
        y_key = round(word["top"] / y_tolerance) * y_tolerance
        if y_key not in rows_by_y:
            rows_by_y[y_key] = []
        rows_by_y[y_key].append(word)

    sorted_y_keys = sorted(rows_by_y.keys())

    # Step 1: Analyze each row to understand its structure
    row_info: list[dict[str, Any]] = []
    for y_key in sorted_y_keys:
        row_words = sorted(rows_by_y[y_key], key=lambda w: w["x0"])
        if not row_words:
            continue

        first_x0 = row_words[0]["x0"]
        last_x1 = row_words[-1]["x1"]
        line_width = last_x1 - first_x0
        combined_text = " ".join(w["text"] for w in row_words)

        # Count distinct x-position groups (potential columns in this row)
        x_positions = [w["x0"] for w in row_words]
        x_groups: list[float] = []
        for x in sorted(x_positions):
            if not x_groups or x - x_groups[-1] > 50:
                x_groups.append(x)

        # A long line of dense text is likely a paragraph, not a table row
        is_paragraph = line_width > page_width * 0.55 and len(combined_text) > 60

        # Partial numbering should not be treated as a table row
        has_partial_numbering = False
        first_word = row_words[0]["text"].strip()
        if PARTIAL_NUMBERING_PATTERN.match(first_word):
            has_partial_numbering = True

        row_info.append(
            {
                "y_key": y_key,
                "words": row_words,
                "text": combined_text,
                "x_groups": x_groups,
                "is_paragraph": is_paragraph,
                "num_columns": len(x_groups),
                "has_partial_numbering": has_partial_numbering,
            }
        )

    # Step 2: Collect all x-positions from rows with 3+ columns to find global column boundaries
    all_table_x_positions: list[float] = []
    for info in row_info:
        if info["num_columns"] >= 3 and not info["is_paragraph"]:
            all_table_x_positions.extend(info["x_groups"])

    if not all_table_x_positions:
        return []

    # Step 3: Compute adaptive column clustering tolerance based on gap analysis
    all_table_x_positions.sort()
    gaps: list[float] = []
    for i in range(len(all_table_x_positions) - 1):
        gap = all_table_x_positions[i + 1] - all_table_x_positions[i]
        if gap > 5:
            gaps.append(gap)

    # Use 70th percentile of gaps as dynamic threshold, clamped between 25 and 50
    if len(gaps) >= 3:
        sorted_gaps = sorted(gaps)
        percentile_70_idx = int(len(sorted_gaps) * 0.70)
        adaptive_tolerance = sorted_gaps[percentile_70_idx]
        adaptive_tolerance = max(25.0, min(50.0, float(adaptive_tolerance)))
    else:
        adaptive_tolerance = 35.0

    # Determine global column X boundaries
    global_columns: list[float] = []
    for x in all_table_x_positions:
        if not global_columns or x - global_columns[-1] > adaptive_tolerance:
            global_columns.append(x)

    # Sanity checks for columns density
    if len(global_columns) <= 1:
        return []

    content_width = global_columns[-1] - global_columns[0]
    avg_col_width = content_width / len(global_columns)
    if avg_col_width < 30:
        return []  # Columns too narrow, likely just dense text spaces

    columns_per_inch = len(global_columns) / max((content_width / 72), 1)
    if columns_per_inch > 10:
        return []  # Density too high

    adaptive_max_columns = int(20 * (page_width / 612))
    adaptive_max_columns = max(15, adaptive_max_columns)
    if len(global_columns) > adaptive_max_columns:
        return []

    # Step 4: Classify rows that align with global columns
    for info in row_info:
        if info["is_paragraph"] or info["has_partial_numbering"]:
            info["is_table_row"] = False
            continue

        aligned_columns: set[int] = set()
        for word in info["words"]:
            word_center_x = (word["x0"] + word["x1"]) / 2.0
            for col_idx, col_x in enumerate(global_columns):
                if abs(word_center_x - col_x) < dynamic_col_tolerance:
                    aligned_columns.add(col_idx)
                    break

        # A valid table row should span at least 2 global columns
        info["is_table_row"] = len(aligned_columns) >= 2

    # Step 5: Find contiguous table regions
    table_regions: list[tuple[int, int]] = []
    i = 0
    while i < len(row_info):
        if row_info[i]["is_table_row"]:
            start_idx = i
            while i < len(row_info) and row_info[i]["is_table_row"]:
                i += 1
            end_idx = i
            table_regions.append((start_idx, end_idx))
        else:
            i += 1

    # Filter out weak tables (must have at least 2 rows to be a meaningful table)
    table_regions = [r for r in table_regions if r[1] - r[0] >= 2]
    if not table_regions:
        return []

    # Step 6: Extract cells for each table region
    extracted_tables: list[tuple[list[list[str]], tuple[float, float, float, float]]] = []
    num_cols = len(global_columns)

    for start, end in table_regions:
        table_data: list[list[str]] = []
        min_x0, min_y0, max_x1, max_y1 = float("inf"), float("inf"), 0.0, 0.0

        for idx in range(start, end):
            info = row_info[idx]
            cells: list[str] = ["" for _ in range(num_cols)]

            for word in info["words"]:
                word_center_x = (word["x0"] + word["x1"]) / 2.0
                # Update table bounding box
                min_x0 = min(min_x0, float(word["x0"]))
                min_y0 = min(min_y0, float(word["top"]))
                max_x1 = max(max_x1, float(word["x1"]))
                max_y1 = max(max_y1, float(word["bottom"]))

                # Assign word to the correct column bucket
                assigned_col = num_cols - 1
                for col_idx in range(num_cols - 1):
                    col_end = global_columns[col_idx + 1]
                    if word_center_x < col_end - (dynamic_col_tolerance / 2):
                        assigned_col = col_idx
                        break

                if cells[assigned_col]:
                    cells[assigned_col] += " " + word["text"]
                else:
                    cells[assigned_col] = word["text"]

            table_data.append([c.strip() for c in cells])

        # Drop entirely empty columns for this specific table
        if table_data:
            valid_cols = [
                col_idx for col_idx in range(num_cols)
                if any(row[col_idx].strip() for row in table_data)
            ]
            if not valid_cols:
                continue

            cleaned_table = [
                [row[col_idx] for col_idx in valid_cols]
                for row in table_data
            ]

            extracted_tables.append((cleaned_table, (min_x0, min_y0, max_x1, max_y1)))

    return extracted_tables
