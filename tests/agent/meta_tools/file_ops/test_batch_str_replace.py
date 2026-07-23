"""Tests for batch_str_replace core."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.core.batch_str_replace import (
    MAX_EDITS_PER_CALL,
    apply_batch_str_replace,
    check_non_overlapping_edits,
    compute_batch_edit_line_range,
    validate_edits_batch,
)
from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import StrReplaceEdit


def test_apply_batch_two_edits_sequential() -> None:
    content = "alpha\nbeta\ngamma"
    edits = (
        StrReplaceEdit(old_str="alpha", new_str="ALPHA"),
        StrReplaceEdit(old_str="gamma", new_str="GAMMA"),
    )
    result, strategies = apply_batch_str_replace(content, edits)
    assert result == "ALPHA\nbeta\nGAMMA"
    assert strategies == ["exact", "exact"]


def test_apply_batch_second_edit_fails_no_partial_apply_in_memory() -> None:
    content = "keep me"
    edits = (
        StrReplaceEdit(old_str="keep", new_str="changed"),
        StrReplaceEdit(old_str="missing", new_str="x"),
    )
    with pytest.raises(ValueError, match="Edit 2"):
        apply_batch_str_replace(content, edits)


def test_overlap_rejected_on_original_content() -> None:
    content = "abcdef"
    edits = (
        StrReplaceEdit(old_str="abc", new_str="1"),
        StrReplaceEdit(old_str="bcd", new_str="2"),
    )
    with pytest.raises(ValueError, match="overlap"):
        check_non_overlapping_edits(content, edits)


def test_max_edits_limit() -> None:
    edits = tuple(StrReplaceEdit(old_str="a", new_str="b") for _ in range(MAX_EDITS_PER_CALL + 1))
    with pytest.raises(ValueError, match=str(MAX_EDITS_PER_CALL)):
        validate_edits_batch(edits)


def test_validate_empty_old_str() -> None:
    with pytest.raises(ValueError, match="old_str cannot be empty"):
        validate_edits_batch((StrReplaceEdit(old_str="", new_str="x"),))


def test_validate_empty_edits() -> None:
    with pytest.raises(ValueError, match="non-empty 'edits'"):
        validate_edits_batch(())


def test_find_exclusive_span_multiple_matches() -> None:
    with pytest.raises(ValueError, match="Found 2 matches"):
        apply_batch_str_replace("aa", (StrReplaceEdit(old_str="a", new_str="b"),))


def test_compute_batch_edit_line_range_empty() -> None:
    start, end = compute_batch_edit_line_range("a\nb\n", ())
    assert start == 1
    assert end == 3


def test_fuzzy_apply_with_hint() -> None:
    from unittest.mock import MagicMock, patch

    fuzzy_result = MagicMock()
    fuzzy_result.success = False
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.core.batch_str_replace.fuzzy_replace",
        return_value=fuzzy_result,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.core.batch_str_replace.find_closest_lines",
        return_value="\nDid you mean line 2?",
    ):
        with pytest.raises(ValueError, match="Did you mean"):
            apply_batch_str_replace("content", (StrReplaceEdit(old_str="missing", new_str="x"),))


def test_apply_preserves_crlf_via_line_endings() -> None:
    content = "a\r\nb\r\n"
    result, _ = apply_batch_str_replace(content, (StrReplaceEdit(old_str="b", new_str="B"),))
    assert "\r\n" in result
