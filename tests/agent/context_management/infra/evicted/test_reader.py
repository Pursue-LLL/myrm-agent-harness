"""Unit tests for evicted file line-range readers."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.agent.context_management.infra.evicted import (
    MAX_STORED_CHARS,
    cap_content_for_storage,
    count_lines_in_text,
    probe_storage_cap_from_tail,
    read_evicted_file_meta,
    read_evicted_line_range,
)


def test_count_lines_in_text_empty() -> None:
    assert count_lines_in_text("") == 0


def test_count_lines_in_text_single_line_no_trailing_newline() -> None:
    assert count_lines_in_text("hello") == 1


def test_count_lines_in_text_multiline() -> None:
    assert count_lines_in_text("a\nb\nc\n") == 3
    assert count_lines_in_text("a\nb\nc") == 3


def test_read_evicted_file_meta(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    meta = read_evicted_file_meta(path)
    assert meta.total_lines == 3
    assert meta.stored_chars == path.stat().st_size


def test_read_evicted_line_range_window(tmp_path: Path) -> None:
    path = tmp_path / "lines.txt"
    path.write_text("".join(f"line-{i}\n" for i in range(10)), encoding="utf-8")

    page = read_evicted_line_range(path, offset=2, limit=3)
    assert page.offset == 2
    assert page.limit == 3
    assert page.total_lines == 10
    assert page.content == "line-2\nline-3\nline-4\n"


def test_read_evicted_line_range_rejects_invalid_offset(tmp_path: Path) -> None:
    path = tmp_path / "lines.txt"
    path.write_text("a\n", encoding="utf-8")
    try:
        read_evicted_line_range(path, offset=-1, limit=1)
    except ValueError as exc:
        assert "offset" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_read_evicted_line_range_rejects_invalid_limit(tmp_path: Path) -> None:
    path = tmp_path / "lines.txt"
    path.write_text("a\n", encoding="utf-8")
    try:
        read_evicted_line_range(path, offset=0, limit=0)
    except ValueError as exc:
        assert "limit" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_probe_storage_cap_from_tail_detects_marker() -> None:
    capped, _ = cap_content_for_storage("x" * (MAX_STORED_CHARS + 10))
    truncated, original = probe_storage_cap_from_tail(capped[-512:])
    assert truncated is True
    assert original == MAX_STORED_CHARS + 10


def test_probe_storage_cap_from_tail_returns_none_on_unparseable_original() -> None:
    from unittest.mock import patch

    tail = "[... stored copy truncated at 2,000,000 chars of 123;"
    with patch(
        "myrm_agent_harness.agent.context_management.infra.evicted.markers.int",
        side_effect=ValueError("forced"),
    ):
        truncated, original = probe_storage_cap_from_tail(tail)
    assert truncated is True
    assert original is None


def test_read_evicted_file_meta_detects_storage_cap(tmp_path: Path) -> None:
    path = tmp_path / "capped.txt"
    capped, _ = cap_content_for_storage("y" * (MAX_STORED_CHARS + 5))
    path.write_text(capped, encoding="utf-8")
    meta = read_evicted_file_meta(path)
    assert meta.storage_truncated is True
    assert meta.original_chars == MAX_STORED_CHARS + 5


def test_read_evicted_line_range_includes_storage_cap_fields(tmp_path: Path) -> None:
    path = tmp_path / "capped.txt"
    capped, _ = cap_content_for_storage("z\n" * (MAX_STORED_CHARS // 2 + 100))
    path.write_text(capped, encoding="utf-8")
    page = read_evicted_line_range(path, offset=0, limit=10)
    assert page.storage_truncated is True
    assert page.original_chars is not None
