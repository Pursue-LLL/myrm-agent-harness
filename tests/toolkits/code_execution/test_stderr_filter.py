"""Tests for line-by-line stderr stream filtering and classification pipeline."""

from myrm_agent_harness.toolkits.code_execution.utils.stderr_filter import (
    ClassifiedStderrLine,
    StderrFilterResult,
    StderrLineSeverity,
    classify_stderr_line,
    filter_stderr_stream_chunk,
    filter_stderr_text,
)


def test_classify_known_info_lines() -> None:
    info_samples = [
        "Reading prompt from stdin...",
        "Reading additional input from stdin...",
        "YOLO mode is enabled for this session",
        "Ripgrep is not available, falling back to git grep",
        "[claude-code:unrecognized_model] using fallback model configuration",
        "Skill git-helper is overriding the built-in skill.",
        "INFO: starting daemon worker process",
        "[DEBUG] raw socket opened on descriptor 7",
    ]
    for line in info_samples:
        classified = classify_stderr_line(line)
        assert classified.severity == StderrLineSeverity.INFO, f"Expected INFO for: {line}"


def test_classify_known_warning_lines() -> None:
    warning_samples = [
        "Warning: This is a development server. Do not use it in a production deployment.",
        "[WARN] Network latency higher than 200ms",
        "npm WARN deprecated request@2.88.2: request has been deprecated",
        "yarn warning package.json: No license field",
        "DeprecationWarning: builtin type dict is deprecated in Python 3.14",
        "UserWarning: torch.meshgrid: in an upcoming release, it will default to indexing='ij'",
        "(node:12345) [DEP0040] DeprecationWarning: The `punycode` module is deprecated.",
    ]
    for line in warning_samples:
        classified = classify_stderr_line(line)
        assert classified.severity == StderrLineSeverity.WARNING, f"Expected WARNING for: {line}"


def test_classify_critical_error_lines() -> None:
    error_samples = [
        "Traceback (most recent call last):",
        "FATAL ERROR: Ineffective mark-compacts near heap limit Allocation failed",
        "PANIC: unhandled runtime panic in goroutine 1",
        "SyntaxError: invalid syntax",
        "ImportError: cannot import name 'foo' from 'bar'",
        "ModuleNotFoundError: No module named 'scipy'",
        "Segmentation fault: 11",
        "bash: line 1: foobar_nonexistent: command not found",
        "/tmp/script.sh: Permission denied",
        "cat: nonexistent.txt: No such file or directory",
    ]
    for line in error_samples:
        classified = classify_stderr_line(line)
        assert classified.severity == StderrLineSeverity.ERROR, f"Expected ERROR for: {line}"


def test_filter_pure_informational_stderr() -> None:
    text = """Reading prompt from stdin...
YOLO mode is enabled
[claude-code:unrecognized_model] provider is openrouter
Warning: dev server running on non-standard port
DeprecationWarning: test warning
"""
    result = filter_stderr_text(text)
    assert not result.has_critical_error
    assert len(result.critical_error_lines) == 0
    assert len(result.info_lines) == 3
    assert len(result.warning_lines) == 2
    assert result.filtered_error_text == ""
    assert "Reading prompt from stdin..." in result.filtered_diagnostic_text


def test_filter_mixed_chunk_prevents_silent_drop_of_fatal_error() -> None:
    """Core regression test against Molio bb06966:
    When a chunk contains informational banners, warnings, AND a real traceback,
    the real error must NEVER be dropped or swallowed.
    """
    mixed_stderr = """Reading prompt from stdin...
[claude-code:unrecognized_model] fallback active
Warning: CPU optimization unavailable
Traceback (most recent call last):
  File "main.py", line 12, in <module>
    raise ValueError("Database connection lost")
ValueError: Database connection lost
YOLO mode is enabled
"""
    result = filter_stderr_text(mixed_stderr)

    # 1. Critical error flag must be raised
    assert result.has_critical_error

    # 2. Traceback block must be cleanly extracted in filtered_error_text
    assert "Traceback (most recent call last):" in result.filtered_error_text
    assert 'raise ValueError("Database connection lost")' in result.filtered_error_text
    assert "ValueError: Database connection lost" in result.filtered_error_text

    # 3. Informational banners and warnings must be in diagnostic stream
    assert "Reading prompt from stdin..." in result.filtered_diagnostic_text
    assert "Warning: CPU optimization unavailable" in result.filtered_diagnostic_text
    assert "YOLO mode is enabled" in result.filtered_diagnostic_text


def test_streaming_chunk_with_line_buffering() -> None:
    chunk1 = "Reading prompt from stdin...\nWarning: low disk"
    lines1, rem_buf1 = filter_stderr_stream_chunk(chunk1)
    assert len(lines1) == 1
    assert lines1[0].severity == StderrLineSeverity.INFO
    assert rem_buf1 == "Warning: low disk"

    # Second chunk finishes the warning line and introduces an error
    chunk2 = " space\nSyntaxError: unexpected EOF\n"
    lines2, rem_buf2 = filter_stderr_stream_chunk(chunk2, buffer=rem_buf1)
    assert len(lines2) == 2
    assert lines2[0].severity == StderrLineSeverity.WARNING
    assert lines2[0].line == "Warning: low disk space"
    assert lines2[1].severity == StderrLineSeverity.ERROR
    assert rem_buf2 == ""
