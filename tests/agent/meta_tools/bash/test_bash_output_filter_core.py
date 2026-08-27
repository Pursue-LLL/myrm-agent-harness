"""Tests for bash_process output line filter."""

from myrm_agent_harness.agent.meta_tools.bash._tool.output_filter_core import (
    compile_output_filter,
    filter_output_lines,
)


def test_filter_output_lines_keeps_matching_only() -> None:
    pattern = compile_output_filter("ERROR|FAIL")
    lines = ["ok line", "ERROR: boom", "still ok", "FAIL hard"]
    assert filter_output_lines(lines, pattern) == ["ERROR: boom", "FAIL hard"]


def test_filter_pattern_length_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="256"):
        compile_output_filter("x" * 257)


def test_filter_output_lines_empty_input() -> None:
    pattern = compile_output_filter("x")
    assert filter_output_lines([], pattern) == []


def test_compile_output_filter_case_insensitive_and_strip() -> None:
    import pytest

    pattern = compile_output_filter("  error|warn  ")
    assert pattern.search("ERROR: uppercase") is not None
    assert pattern.search("warn: lowercase") is not None
    assert pattern.search("ok line") is None

    with pytest.raises(ValueError, match="cannot be empty"):
        compile_output_filter("   ")

