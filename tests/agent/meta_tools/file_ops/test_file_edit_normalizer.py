"""Tests for file_edit_normalizer."""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.file_edit_normalizer import (
    merge_edits_for_diff,
    normalize_edits_payload,
)
from myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool import FileEditInput


def test_normalize_flat_old_new() -> None:
    edits = normalize_edits_payload({"old_str": "a", "new_str": "b"})
    assert edits == [{"old_str": "a", "new_str": "b"}]


def test_normalize_edits_json_string() -> None:
    payload = {"edits": json.dumps([{"old_str": "x", "new_str": "y"}])}
    edits = normalize_edits_payload(payload)
    assert edits == [{"old_str": "x", "new_str": "y"}]


def test_file_edit_input_model_accepts_legacy_flat_fields() -> None:
    parsed = FileEditInput.model_validate(
        {"path": "f.py", "old_str": "1", "new_str": "2"}
    )
    assert len(parsed.edits) == 1
    assert parsed.edits[0].old_str == "1"


def test_merge_edits_for_diff_multiple() -> None:
    old, new = merge_edits_for_diff(
        [{"old_str": "a", "new_str": "A"}, {"old_str": "b", "new_str": "B"}]
    )
    assert "--- edit 1 ---" in old
    assert "--- edit 2 ---" in new


def test_normalize_requires_edits_or_legacy() -> None:
    with pytest.raises(ValueError, match="requires edits"):
        normalize_edits_payload({"path": "x"})


def test_coerce_old_string_aliases() -> None:
    edits = normalize_edits_payload({"old_string": "a", "new_string": "b"})
    assert edits == [{"old_str": "a", "new_str": "b"}]


def test_coerce_edit_item_old_string_in_array() -> None:
    edits = normalize_edits_payload({"edits": [{"old_string": "x", "new_string": "y"}]})
    assert edits == [{"old_str": "x", "new_str": "y"}]


def test_coerce_edit_item_missing_old_str() -> None:
    with pytest.raises(ValueError, match="requires old_str"):
        normalize_edits_payload({"edits": [{"new_str": "only"}]})


def test_coerce_edit_item_not_mapping() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        normalize_edits_payload({"edits": ["bad"]})


def test_edits_json_not_array() -> None:
    with pytest.raises(ValueError, match="must decode to an array"):
        normalize_edits_payload({"edits": json.dumps({"x": 1})})


def test_edits_not_sequence() -> None:
    with pytest.raises(ValueError, match="must be an array"):
        normalize_edits_payload({"edits": 123})


def test_merge_edits_for_diff_empty() -> None:
    assert merge_edits_for_diff([]) == ("", "")


def test_merge_edits_for_diff_single() -> None:
    old, new = merge_edits_for_diff([{"old_str": "a", "new_str": "b"}])
    assert old == "a" and new == "b"
