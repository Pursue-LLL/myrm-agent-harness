"""Unit tests for TerminalLogDistiller.

Tests ANSI code stripping, carriage return progress clearing, error pattern detection,
tail window preservation, and token compression metrics.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.code_execution.utils.log_distiller import (
    DistilledLogResult,
    clean_terminal_noise,
    distill_terminal_output,
    is_progress_noise_line,
)


def test_clean_terminal_noise_ansi_and_carriage_return() -> None:
    # Text with ANSI colors and \r progress rewrite
    raw = "\x1b[32mStarting build...\x1b[0m\r\x1b[33mProgress: 10%\x1b[0m\r\x1b[32mProgress: 100% Done\x1b[0m\nNext step"
    cleaned = clean_terminal_noise(raw)
    assert "Starting build..." not in cleaned
    assert "Progress: 100% Done" in cleaned
    assert "Next step" in cleaned
    assert "\x1b[" not in cleaned


def test_is_progress_noise_line() -> None:
    assert is_progress_noise_line(" [ 45% ] Building C object") is True
    assert is_progress_noise_line("80% [==================>     ]") is True
    assert is_progress_noise_line("downloading package 1.2MB/s") is True
    assert is_progress_noise_line("npm ERR! code E404") is False
    assert is_progress_noise_line("fatal: destination path already exists") is False


def test_distill_short_output_bypass() -> None:
    short_log = "Line 1: init\nLine 2: done\n"
    res = distill_terminal_output(short_log)
    assert res.original_line_count == 2
    assert res.distilled_line_count == 2
    assert res.compression_ratio == 1.0
    assert "Line 1: init" in res.distilled_text


def test_distill_long_noisy_build_log_with_error_anchor() -> None:
    # Generate 300 lines of noisy progress followed by a fatal error and tail
    lines: list[str] = ["Building project..."]
    for i in range(1, 150):
        lines.append(f"[{i}%] Compiling chunk {i}.js ... downloading 2.4MB/s")
    
    # Inject critical error anchor in the middle
    lines.append("TypeError: Cannot find module '@types/node'")
    lines.append("    at Function.Module._resolveFilename (node:internal/modules/cjs/loader:1077:15)")
    lines.append("npm ERR! A complete log of this run can be found in /root/.npm/_logs/error.log")

    for i in range(151, 280):
        lines.append(f"[{i}%] Compiling fallback {i}.js")

    # Tail exit state
    lines.append("Build failed with exit code 1")
    lines.append("Fatal error occurred during bundle synthesis")

    raw_output = "\n".join(lines)
    res = distill_terminal_output(raw_output, max_lines=40, raw_log_path="/tmp/build.log")

    assert res.original_line_count > 250
    assert res.distilled_line_count <= 40 + 5  # footer included
    assert res.compression_ratio < 0.3
    assert "MODULE_NOT_FOUND" in res.matched_error_tags or "FATAL_PANIC" in res.matched_error_tags
    assert "Cannot find module" in res.distilled_text
    assert "Build failed with exit code 1" in res.distilled_text
    assert "[Raw full log saved at: /tmp/build.log]" in res.distilled_text


def test_distill_empty_input() -> None:
    res = distill_terminal_output("")
    assert res.distilled_text == ""
    assert res.original_line_count == 0
