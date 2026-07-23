"""Batch string-replace application for file edits.

[INPUT]
- utils.fuzzy_match::fuzzy_replace, find_closest_lines (POS: Progressive fuzzy match chain)
- core.file_conflict_guard::compute_edit_line_range (POS: Edit line range calculator)
- core.operation_context::StrReplaceEdit (POS: Single edit payload)
- utils.line_endings::detect_line_ending, normalize_line_endings (POS: CRLF/LF preservation)

[OUTPUT]
- apply_batch_str_replace: In-memory sequential batch apply
- validate_edits_batch, check_non_overlapping_edits, compute_batch_edit_line_range

[POS]
Batch str-replace engine. Applies up to MAX_EDITS edits in one in-memory pass before a single disk write.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from myrm_agent_harness.utils.fuzzy_match import find_closest_lines, fuzzy_replace

from .file_conflict_guard import compute_edit_line_range
from .operation_context import StrReplaceEdit

logger = logging.getLogger(__name__)

MAX_EDITS_PER_CALL = 20


def validate_edits_batch(edits: Sequence[StrReplaceEdit]) -> None:
    """Validate edit count and non-empty old_str entries."""
    if not edits:
        raise ValueError("STR_REPLACE operation requires non-empty 'edits'")
    if len(edits) > MAX_EDITS_PER_CALL:
        raise ValueError(
            f"At most {MAX_EDITS_PER_CALL} edits per call (got {len(edits)})"
        )
    for index, edit in enumerate(edits, start=1):
        if not edit.old_str:
            raise ValueError(f"Edit {index}: old_str cannot be empty")


def _find_exclusive_span(content: str, old_str: str) -> tuple[int, int] | None:
    idx = content.find(old_str)
    if idx < 0:
        return None
    count = content.count(old_str)
    if count > 1:
        raise ValueError(
            f"Found {count} matches. Please provide more context to make the match unique."
        )
    return idx, idx + len(old_str)


def check_non_overlapping_edits(content: str, edits: Sequence[StrReplaceEdit]) -> None:
    """Reject edits whose exact-match spans overlap in the original file."""
    ranges: list[tuple[int, int]] = []
    for i, edit in enumerate(edits):
        span = _find_exclusive_span(content, edit.old_str)
        if span is None:
            continue
        start, end = span
        for j, (prev_start, prev_end) in enumerate(ranges):
            if not (end <= prev_start or start >= prev_end):
                raise ValueError(
                    f"Edits {j + 1} and {i + 1} overlap in the original file; "
                    "merge into one edit or reorder so regions are disjoint."
                )
        ranges.append((start, end))


def compute_batch_edit_line_range(
    content: str, edits: Sequence[StrReplaceEdit]
) -> tuple[int, int]:
    """Union of 1-indexed line ranges affected by all edits on original content."""
    if not edits:
        total = content.count("\n") + 1
        return 1, total
    starts: list[int] = []
    ends: list[int] = []
    for edit in edits:
        start, end = compute_edit_line_range(content, edit.old_str)
        starts.append(start)
        ends.append(end)
    return min(starts), max(ends)


def apply_batch_str_replace(
    content: str, edits: Sequence[StrReplaceEdit]
) -> tuple[str, list[str]]:
    """Apply edits sequentially in memory. Returns (new_content, strategies_used)."""
    from ..utils.line_endings import detect_line_ending, normalize_line_endings

    validate_edits_batch(edits)
    check_non_overlapping_edits(content, edits)

    original_eol = detect_line_ending(content)
    current = content
    strategies: list[str] = []

    for index, edit in enumerate(edits, start=1):
        if edit.old_str in current:
            count = current.count(edit.old_str)
            if count > 1:
                raise ValueError(
                    f"Edit {index}: found {count} matches. Please provide more context to make the match unique."
                )
            current = current.replace(edit.old_str, edit.new_str, 1)
            strategies.append("exact")
            continue

        result = fuzzy_replace(current, edit.old_str, edit.new_str)
        if result.success:
            logger.info(
                "Fuzzy match succeeded: strategy=%s confidence=%.2f edit_index=%d",
                result.strategy,
                result.confidence,
                index,
            )
            current = result.content
            strategies.append(result.strategy)
            continue

        err_msg = (
            f"Edit {index}: text not found in file.\nSearched for:\n{edit.old_str}"
        )
        hint = find_closest_lines(edit.old_str, current)
        if hint:
            err_msg += hint
        raise ValueError(err_msg)

    if original_eol:
        current = normalize_line_endings(current, original_eol)
    return current, strategies


__all__ = [
    "MAX_EDITS_PER_CALL",
    "apply_batch_str_replace",
    "check_non_overlapping_edits",
    "compute_batch_edit_line_range",
    "validate_edits_batch",
]
