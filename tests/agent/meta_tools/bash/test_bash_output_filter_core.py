"""Tests for bash_process output line filter."""

from myrm_agent_harness.agent.meta_tools.bash._bash_output_filter_core import (
    compile_output_filter,
    filter_output_lines,
)


def test_filter_output_lines_keeps_matching_only() -> None:
    pattern = compile_output_filter("ERROR|FAIL")
    lines = ["ok line", "ERROR: boom", "still ok", "FAIL hard"]
    assert filter_output_lines(lines, pattern) == ["ERROR: boom", "FAIL hard"]


def test_filter_output_lines_empty_input() -> None:
    pattern = compile_output_filter("x")
    assert filter_output_lines([], pattern) == []
