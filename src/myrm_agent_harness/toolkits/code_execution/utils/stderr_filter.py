"""Line-by-line stderr stream processing and classification pipeline.

[INPUT]
- None (pure functional classification and streaming utility)

[OUTPUT]
- StderrLineSeverity: Enum of stderr classifications (INFO, WARNING, ERROR, RAW)
- ClassifiedStderrLine: Dataclass representing a classified line
- StderrFilterResult: Dataclass summarizing filtered stderr stream results
- classify_stderr_line: Single line classification function
- filter_stderr_text: Batch line-by-line stderr filtering pipeline
- filter_stderr_stream_chunk: Streaming chunk adapter with line-buffering support

[POS]
Harness-level line-by-line stderr filter inspired by Molio bb06966.
Replaces brittle whole-block substring matching with fine-grained per-line classification.
Prevents real exceptions and panics from being dropped when mixed with CLI banners and warnings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, unique


@unique
class StderrLineSeverity(Enum):
    """Classification severity for individual stderr lines."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    RAW = "raw"


@dataclass(frozen=True)
class ClassifiedStderrLine:
    """A single classified stderr line."""

    line: str
    severity: StderrLineSeverity
    pattern_matched: str | None = None


@dataclass(frozen=True)
class StderrFilterResult:
    """Aggregated result of filtering a stderr stream block."""

    raw_stderr: str
    critical_error_lines: tuple[str, ...]
    warning_lines: tuple[str, ...]
    info_lines: tuple[str, ...]
    has_critical_error: bool
    filtered_error_text: str
    filtered_diagnostic_text: str


# Precompiled regular expressions for high-throughput line matching
_RE_INFO_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^Reading prompt from stdin", re.IGNORECASE),
    re.compile(r"^Reading additional input from stdin", re.IGNORECASE),
    re.compile(r"^YOLO mode is enabled", re.IGNORECASE),
    re.compile(r"^Ripgrep is not available", re.IGNORECASE),
    re.compile(r"^\[claude-code:[a-z0-9_-]+\]", re.IGNORECASE),
    re.compile(r"is overriding the built-in skill\.?$", re.IGNORECASE),
    re.compile(r"^(?:INFO|DEBUG):\s*", re.IGNORECASE),
    re.compile(r"^\[(?:INFO|DEBUG)\]\s*", re.IGNORECASE),
    re.compile(r"^\s*fetching\s+", re.IGNORECASE),
)

_RE_WARNING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^Warning:\s*", re.IGNORECASE),
    re.compile(r"^\[(?:WARN|WARNING)\]\s*", re.IGNORECASE),
    re.compile(r"^(?:npm\s+WARN|yarn\s+warning)", re.IGNORECASE),
    re.compile(r"\b(?:DeprecationWarning|UserWarning|FutureWarning|ExperimentalWarning):", re.IGNORECASE),
    re.compile(r"^\(node:\d+\)\s+\[DEP[0-9A-Z]+\]", re.IGNORECASE),
)

_RE_CRITICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^Traceback \(most recent call last\):"),
    re.compile(r"^(?:FATAL(?:\s+ERROR)?:|PANIC:|panic:)\s*", re.IGNORECASE),
    re.compile(r"^(?:Error|Exception):\s*", re.IGNORECASE),
    re.compile(r"\b(?:SyntaxError|ImportError|ModuleNotFoundError|NameError|TypeError|ValueError|IndexError|KeyError|AttributeError|ZeroDivisionError|RuntimeError|AssertionError|FileNotFoundError|PermissionError):\s*"),
    re.compile(r"\bSegmentation fault\b", re.IGNORECASE),
    re.compile(r"\bcommand not found\b", re.IGNORECASE),
    re.compile(r"\bNo such file or directory\b", re.IGNORECASE),
    re.compile(r"\bPermission denied\b", re.IGNORECASE),
    re.compile(r"\bKilled\s*$", re.IGNORECASE),
)


def classify_stderr_line(raw_line: str) -> ClassifiedStderrLine:
    """Classify a single stderr line based on diagnostic heuristics.

    Args:
        raw_line: The raw stderr line to inspect.

    Returns:
        ClassifiedStderrLine instance with severity and matched pattern.
    """
    stripped = raw_line.strip()
    if not stripped:
        return ClassifiedStderrLine(line=raw_line, severity=StderrLineSeverity.RAW)

    # 1. Critical errors take precedence if explicitly detected
    for pattern in _RE_CRITICAL_PATTERNS:
        if pattern.search(stripped):
            return ClassifiedStderrLine(
                line=raw_line,
                severity=StderrLineSeverity.ERROR,
                pattern_matched=pattern.pattern,
            )

    # 2. Known informational banners and headless tool diagnostics
    for pattern in _RE_INFO_PATTERNS:
        if pattern.search(stripped):
            return ClassifiedStderrLine(
                line=raw_line,
                severity=StderrLineSeverity.INFO,
                pattern_matched=pattern.pattern,
            )

    # 3. Known warning prefixes
    for pattern in _RE_WARNING_PATTERNS:
        if pattern.search(stripped):
            return ClassifiedStderrLine(
                line=raw_line,
                severity=StderrLineSeverity.WARNING,
                pattern_matched=pattern.pattern,
            )

    # 4. Fallback to RAW for non-pattern matching stderr lines
    return ClassifiedStderrLine(line=raw_line, severity=StderrLineSeverity.RAW)


def filter_stderr_text(text: str) -> StderrFilterResult:
    """Filter and classify a full stderr output block line-by-line.

    Guarantees that informational banners or warnings in the same chunk
    never suppress genuine exceptions or panic traces.

    Args:
        text: Complete or chunked stderr string.

    Returns:
        StderrFilterResult with grouped lines and cleanly separated streams.
    """
    if not text:
        return StderrFilterResult(
            raw_stderr="",
            critical_error_lines=(),
            warning_lines=(),
            info_lines=(),
            has_critical_error=False,
            filtered_error_text="",
            filtered_diagnostic_text="",
        )

    critical_lines: list[str] = []
    warning_lines: list[str] = []
    info_lines: list[str] = []
    diagnostic_lines: list[str] = []

    # Traceback capture state machine to preserve entire traceback blocks
    in_python_traceback = False

    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("Traceback (most recent call last):"):
            in_python_traceback = True
            critical_lines.append(line)
            continue

        if in_python_traceback:
            critical_lines.append(line)
            # A typical traceback ends on the error line (e.g. "ValueError: foo")
            if re.match(r"^[A-Za-z0-9_]+Error:\s*", stripped) or re.match(r"^[A-Za-z0-9_]+Exception:\s*", stripped):
                in_python_traceback = False
            continue

        classified = classify_stderr_line(line)
        if classified.severity == StderrLineSeverity.ERROR:
            critical_lines.append(line)
        elif classified.severity == StderrLineSeverity.WARNING:
            warning_lines.append(line)
            diagnostic_lines.append(line)
        elif classified.severity == StderrLineSeverity.INFO:
            info_lines.append(line)
            diagnostic_lines.append(line)
        else:
            # RAW lines: if there's no critical error detected yet, consider as diagnostic
            diagnostic_lines.append(line)

    has_critical = len(critical_lines) > 0
    error_text = "\n".join(critical_lines)
    diag_text = "\n".join(diagnostic_lines)

    return StderrFilterResult(
        raw_stderr=text,
        critical_error_lines=tuple(critical_lines),
        warning_lines=tuple(warning_lines),
        info_lines=tuple(info_lines),
        has_critical_error=has_critical,
        filtered_error_text=error_text,
        filtered_diagnostic_text=diag_text,
    )


def filter_stderr_stream_chunk(
    chunk: str,
    buffer: str = "",
) -> tuple[list[ClassifiedStderrLine], str]:
    """Process an incremental stderr stream chunk with newline buffering.

    Args:
        chunk: The incoming chunk of stderr text.
        buffer: Accumulated partial line buffer from prior chunks.

    Returns:
        A tuple of (classified lines in this chunk, remaining incomplete buffer).
    """
    combined = buffer + chunk
    if "\n" not in combined and "\r" not in combined:
        return [], combined

    raw_lines = combined.splitlines(keepends=True)
    results: list[ClassifiedStderrLine] = []
    rem_buffer = ""

    # Check if the last element ends with a newline delimiter
    if raw_lines and not (raw_lines[-1].endswith("\n") or raw_lines[-1].endswith("\r")):
        rem_buffer = raw_lines.pop()

    for item in raw_lines:
        cleaned = item.rstrip("\r\n")
        if cleaned:
            results.append(classify_stderr_line(cleaned))

    return results, rem_buffer
