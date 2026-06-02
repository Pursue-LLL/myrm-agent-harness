"""Unit tests for the background progress-line parser (R2 + R3)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.bash._background_progress import (
    try_parse_progress_line,
)


def test_returns_none_for_blank_input() -> None:
    assert try_parse_progress_line("") is None
    assert try_parse_progress_line("noise without signal") is None


def test_explicit_marker_with_percent_and_message() -> None:
    payload = try_parse_progress_line('MYRM_PROGRESS {"percent": 73, "message": "Bundling JS"}')
    assert payload is not None
    assert payload["progress"] == 73
    assert payload["message"] == "Bundling JS"


def test_explicit_marker_with_current_total_derives_percent() -> None:
    payload = try_parse_progress_line('MYRM_PROGRESS {"current": 3, "total": 10, "message": "Tests"}')
    assert payload is not None
    assert payload["progress"] == 30
    assert payload["step_index"] == 3
    assert payload["total_steps"] == 10


def test_explicit_marker_clamps_percent() -> None:
    payload = try_parse_progress_line('MYRM_PROGRESS {"percent": 250}')
    assert payload is not None
    assert payload["progress"] == 100

    payload_neg = try_parse_progress_line('MYRM_PROGRESS {"percent": -10}')
    assert payload_neg is not None
    assert payload_neg["progress"] == 0


def test_checkpoint_marker_emits_category() -> None:
    payload = try_parse_progress_line('MYRM_CHECKPOINT {"message": "Cache warmed"}')
    assert payload is not None
    assert payload["message"] == "Cache warmed"
    assert payload["category"] == "background:checkpoint"


def test_invalid_marker_payload_returns_none() -> None:
    assert try_parse_progress_line("MYRM_PROGRESS not-json") is None


def test_heuristic_percent_pattern() -> None:
    payload = try_parse_progress_line(" Building... 42% complete")
    assert payload is not None
    assert payload["progress"] == 42


def test_heuristic_fraction_with_unit_does_not_set_step_counter() -> None:
    payload = try_parse_progress_line("Downloaded 1.5 / 3.0 GiB")
    assert payload is not None
    assert payload["progress"] == 50
    assert "step_index" not in payload


def test_heuristic_integer_fraction_sets_step_counter() -> None:
    payload = try_parse_progress_line("3 / 10 tests passed")
    assert payload is not None
    assert payload["progress"] == 30
    assert payload["step_index"] == 3
    assert payload["total_steps"] == 10


def test_heuristic_phase_only_emits_message() -> None:
    payload = try_parse_progress_line("Compiling main.rs")
    assert payload is not None
    assert payload["message"] == "Compiling main.rs"
    assert "progress" not in payload


@pytest.mark.parametrize("line", ["INFO foo", "Build OK", "warning: bar"])
def test_unrelated_lines_return_none(line: str) -> None:
    assert try_parse_progress_line(line) is None


@pytest.mark.parametrize(
    "line",
    [
        "npm ERR! Disk 99% full",
        "ERROR: Compiling failed at 42%",
        "FATAL: heap usage 87%",
        "Traceback (most recent call last): 1 / 10 frames",
        "panic: runtime error at 50%",
        "Exception in thread main: 3 / 4 retries left",
    ],
)
def test_error_lines_never_emit_progress(line: str) -> None:
    """O6: stderr-style error markers must not be parsed as build progress."""
    assert try_parse_progress_line(line) is None
