from myrm_agent_harness.agent.meta_tools.file_ops.core.file_read_truncation import (
    _last_gutter_line_number,
    truncate_file_output as _truncate_file_output,
)
from myrm_agent_harness.agent.meta_tools.file_ops.core.result_formatter import clamp_line
from myrm_agent_harness.agent.meta_tools.file_ops.utils.line_endings import strip_utf8_bom


def test_gutter_line_number_empty_returns_none():
    """Empty line list yields no gutter continuation offset."""
    assert _last_gutter_line_number([]) is None
    assert _last_gutter_line_number(["no gutter here"]) is None
    assert _last_gutter_line_number(["    42|content"]) == 42


def test_truncate_file_output_no_truncation():
    output = "short text"
    truncated, was_truncated, meta = _truncate_file_output(output, max_chars=100)
    assert truncated == "short text"
    assert was_truncated is False
    assert meta == {}


def test_truncate_file_output_with_truncation():
    output = "a" * 200
    truncated, was_truncated, meta = _truncate_file_output(output, max_chars=100, is_dir=False, path_str="test.txt")
    assert was_truncated is True
    assert "SYSTEM WARNING" in truncated
    assert meta["type"] == "file"
    assert meta["path"] == "test.txt"
    assert meta["total_lines"] == 1
    assert meta["shown_chars"] == 100
    assert "total_mb" in meta

    assert "Use test.txt:2- to continue" in truncated
    assert "grep" not in truncated
    assert "bash_exec" not in truncated


def test_truncate_file_output_includes_actual_path_in_hint():
    """Continuation hint must include the actual file path (as a line number)."""
    output = "a" * 200
    truncated, _, _ = _truncate_file_output(output, max_chars=100, is_dir=False, path_str="src/app.py")
    assert "src/app.py:2- to continue" in truncated


def test_truncate_file_output_at_exact_boundary():
    """Output exactly at max_chars should not be truncated."""
    output = "a" * 100
    truncated, was_truncated, meta = _truncate_file_output(output, max_chars=100)
    assert was_truncated is False
    assert truncated == output
    assert meta == {}


def test_truncate_dir_output_with_truncation():
    output = "a" * 200
    truncated, was_truncated, meta = _truncate_file_output(output, max_chars=100, is_dir=True, path_str="test_dir")
    assert was_truncated is True
    assert "truncated" in truncated
    assert meta["type"] == "dir"
    assert meta["path"] == "test_dir"


def test_truncate_preserves_complete_line_boundary():
    """Truncation must cut at the last complete line, not mid-line."""
    output = "line1\nline2\nline3\nline4"
    truncated, was_truncated, _ = _truncate_file_output(
        output, max_chars=10, is_dir=False, path_str="f.py"
    )
    assert was_truncated is True
    # Only full lines "line1" fits in 10 chars; the rest are dropped.
    assert truncated.startswith("line1")
    assert "line2" not in truncated


def test_truncate_computes_next_offset_from_gutter():
    """With a line-number gutter, next_offset is the last shown line + 1."""
    output = "\n".join(f"{i:6}|content {i}" for i in range(1, 21))
    truncated, was_truncated, meta = _truncate_file_output(
        output, max_chars=100, is_dir=False, path_str="big.py"
    )
    assert was_truncated is True
    assert meta["next_offset"] > 1
    assert f"Use big.py:{meta['next_offset']}- to continue" in truncated


def test_truncate_no_gutter_falls_back_to_line_offset():
    """Without a gutter, the continuation hint falls back to retained-line + 1
    (a line number, matching vault:: parse semantics — never a char count)."""
    output = "x" * 500
    truncated, was_truncated, meta = _truncate_file_output(
        output, max_chars=100, is_dir=False, path_str="raw.txt"
    )
    assert was_truncated is True
    assert "raw.txt:2- to continue" in truncated
    assert meta["next_offset"] == 2


def test_truncate_respects_max_lines():
    """Line-count cap bounds output independent of char budget."""
    output = "\n".join(f"line{i}" for i in range(1, 200))
    truncated, was_truncated, meta = _truncate_file_output(
        output, max_chars=100000, is_dir=False, path_str="many.py", max_lines=10
    )
    assert was_truncated is True
    # The capped body keeps exactly 10 lines (marker/hint appended after).
    body = truncated.split("\n\n... [truncated]")[0]
    assert body.count("\n") + 1 == 10
    assert meta["total_lines"] == 199


def test_clamp_line_short_lines_unchanged():
    assert clamp_line("hello", 2000) == "hello"


def test_clamp_line_long_line_gets_marker():
    clamped = clamp_line("a" * 100, 10)
    assert clamped == f"{'a' * 10}... [truncated]"


def test_clamp_line_none_disabled():
    assert clamp_line("a" * 100, None) == "a" * 100


def test_strip_utf8_bom_removes_bom():
    assert strip_utf8_bom("\ufeffhello") == "hello"
    assert strip_utf8_bom("hello") == "hello"


def test_truncate_empty_string_not_truncated():
    """Empty output is never truncated (no marker, no metadata)."""
    truncated, was_truncated, meta = _truncate_file_output("", max_chars=100, path_str="empty.txt")
    assert was_truncated is False
    assert truncated == ""
    assert meta == {}


