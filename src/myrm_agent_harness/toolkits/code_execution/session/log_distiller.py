"""High-efficiency terminal execution log distiller.

Cleans ANSI escape noise, filters out repetitive terminal progress bar overwrites,
anchors critical error signal windows, preserves tail exit state, and compresses
thousands of lines of noisy build/deploy logs into a high-signal diagnostic
snippet (<= 50 lines), reducing token consumption by 90%+ while maximizing
prompt cache hit rates.

[INPUT]
- raw_output: str, exit_code: int, raw_log_path: str
- myrm_agent_harness.utils.text_utils::strip_ansi

[OUTPUT]
- DistilledLogResult: Typed container for distilled log snippet and metrics.
- TerminalLogDistiller: Core stateless log distillation and anomaly anchoring engine.

[POS]
myrm_agent_harness.toolkits.code_execution.session.log_distiller
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Pattern

from myrm_agent_harness.utils.text_utils import strip_ansi

_PROGRESS_LINE_PATTERNS: Final[tuple[Pattern[str], ...]] = (
    re.compile(r"^\s*\[\s*\d+%\s*\]", re.IGNORECASE),
    re.compile(r"^\s*\d+%\s*\[[=>\s-]+\]", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:kB|MB|GB|B)/s\b", re.IGNORECASE),
    re.compile(r"^\s*Downloading\s+\S+\s*\(\d+%\)", re.IGNORECASE),
    re.compile(r"^\s*Fetching\s+\S+\s*\.\.\.", re.IGNORECASE),
    re.compile(r"^\s*(?:#+|\.+|\*+)\s*$", re.IGNORECASE),
)

_ERROR_SIGNAL_PATTERNS: Final[tuple[Pattern[str], ...]] = (
    re.compile(r"\b(?:401\s+Unauthorized|403\s+Forbidden|426\s+Upgrade\s+Required|502\s+Bad\s+Gateway)\b", re.IGNORECASE),
    re.compile(r"\b(?:EADDRINUSE|ECONNREFUSED|ETIMEDOUT|ECONNRESET|ENOTFOUND)\b"),
    re.compile(r"\b(?:Permission\s+denied|Access\s+denied|Operation\s+not\s+permitted)\b", re.IGNORECASE),
    re.compile(r"\b(?:npm\s+ERR!|yarn\s+error|pip\s+error|fatal:\s+|panic:\s+|SIGSEGV|OutOfMemoryError)\b", re.IGNORECASE),
    re.compile(r"\b(?:Traceback\s+\(most\s+recent\s+call\s+last\):|SyntaxError:|TypeError:|ValueError:|KeyError:)\b"),
    re.compile(r"\b(?:error\[E\d+\]:|error:\s+|FAILED\b|CMake\s+Error|make:\s+\*\*\*)\b", re.IGNORECASE),
    re.compile(r"\b(?:nginx:\s+\[emerg\]|nginx:\s+\[alert\]|systemctl:\s+Job\s+failed)\b", re.IGNORECASE),
)

_MAX_UNCOMPRESSED_LINES: Final[int] = 80
_MAX_UNCOMPRESSED_BYTES: Final[int] = 4096
_DEFAULT_TARGET_LINES: Final[int] = 50
_TAIL_WINDOW_SIZE: Final[int] = 25
_CONTEXT_WINDOW_SIZE: Final[int] = 2


@dataclass(frozen=True)
class DistilledLogResult:
    """Typed envelope containing the distilled text snippet and compression metrics."""

    distilled_text: str
    original_line_count: int
    distilled_line_count: int
    error_anchor_count: int
    raw_log_path: str
    is_distilled: bool
    token_saving_ratio: float


class TerminalLogDistiller:
    """Stateless high-density terminal log distillation engine."""

    @classmethod
    def clean_terminal_noise(cls, text: str) -> list[str]:
        """Strip ANSI escapes, resolve carriage return overwrites, and drop progress noise."""
        clean_text = strip_ansi(text)
        raw_lines = clean_text.splitlines()
        filtered_lines: list[str] = []

        for line in raw_lines:
            # Handle terminal carriage return overwrite (e.g. "Progress 10%\rProgress 20%")
            if "\r" in line:
                segments = line.split("\r")
                line = segments[-1] if segments[-1].strip() else (segments[-2] if len(segments) > 1 else "")

            stripped = line.strip()
            if not stripped:
                continue

            # Check if line is purely a transient progress bar update
            is_progress = any(pat.search(stripped) for pat in _PROGRESS_LINE_PATTERNS)
            if is_progress:
                continue

            filtered_lines.append(line)

        return filtered_lines

    @classmethod
    def extract_error_anchor_indices(cls, lines: list[str]) -> list[int]:
        """Find 0-indexed line numbers containing critical error signals."""
        anchor_indices: list[int] = []
        for idx, line in enumerate(lines):
            for pat in _ERROR_SIGNAL_PATTERNS:
                if pat.search(line):
                    anchor_indices.append(idx)
                    break
        return anchor_indices

    @classmethod
    def distill(
        cls,
        raw_output: str,
        *,
        max_output_lines: int = _DEFAULT_TARGET_LINES,
        raw_log_path: str = "",
        exit_code: int = 0,
    ) -> DistilledLogResult:
        """Compress noisy terminal log output into a high-density diagnostic snippet.

        If the log is short (<= 80 lines & <= 4KB), returns the cleaned original.
        Otherwise, composes error anchors + tail window + metadata footer.
        """
        cleaned_lines = cls.clean_terminal_noise(raw_output)
        original_line_count = len(cleaned_lines)
        total_raw_bytes = len(raw_output.encode("utf-8", errors="ignore"))

        if original_line_count <= _MAX_UNCOMPRESSED_LINES and total_raw_bytes <= _MAX_UNCOMPRESSED_BYTES:
            distilled_content = "\n".join(cleaned_lines)
            return DistilledLogResult(
                distilled_text=distilled_content,
                original_line_count=original_line_count,
                distilled_line_count=original_line_count,
                error_anchor_count=0,
                raw_log_path=raw_log_path,
                is_distilled=False,
                token_saving_ratio=0.0,
            )

        # 1. Locate all error signal line indices
        anchor_indices = cls.extract_error_anchor_indices(cleaned_lines)

        # 2. Collect lines to include (anchors with context + tail window)
        included_indices: set[int] = set()

        # Add error anchors with surrounding context
        for anchor_idx in anchor_indices:
            start = max(0, anchor_idx - _CONTEXT_WINDOW_SIZE)
            end = min(original_line_count, anchor_idx + _CONTEXT_WINDOW_SIZE + 1)
            for i in range(start, end):
                included_indices.add(i)

        # Add tail window
        tail_start = max(0, original_line_count - _TAIL_WINDOW_SIZE)
        for i in range(tail_start, original_line_count):
            included_indices.add(i)

        sorted_indices = sorted(included_indices)

        # 3. Assemble formatted snippet with omission indicators
        snippet_parts: list[str] = []
        snippet_parts.append(f"--- [DISTILLED LOG: {original_line_count} lines -> top signals, exit_code={exit_code}] ---")

        last_idx = -1
        current_lines_budget = max_output_lines - 4  # Reserve lines for headers and footer
        lines_written = 0

        for idx in sorted_indices:
            if lines_written >= current_lines_budget:
                snippet_parts.append(f"... [{original_line_count - idx} additional lines omitted] ...")
                break

            if last_idx != -1 and idx > last_idx + 1:
                omitted_count = idx - last_idx - 1
                snippet_parts.append(f"... [{omitted_count} noisy/progress lines omitted] ...")
                lines_written += 1

            snippet_parts.append(f"L{idx + 1}: {cleaned_lines[idx]}")
            lines_written += 1
            last_idx = idx

        # 4. Append metadata footer
        footer_elements: list[str] = [
            f"--- [END DISTILLED | Anchors: {len(anchor_indices)}",
        ]
        if raw_log_path:
            footer_elements.append(f"| Raw log: {raw_log_path}")
        footer_elements.append("] ---")
        snippet_parts.append(" ".join(footer_elements))

        distilled_text = "\n".join(snippet_parts)
        distilled_line_count = len(snippet_parts)
        saving_ratio = max(0.0, 1.0 - (distilled_line_count / max(1, original_line_count)))

        return DistilledLogResult(
            distilled_text=distilled_text,
            original_line_count=original_line_count,
            distilled_line_count=distilled_line_count,
            error_anchor_count=len(anchor_indices),
            raw_log_path=raw_log_path,
            is_distilled=True,
            token_saving_ratio=round(saving_ratio, 4),
        )


def distill_terminal_output(
    raw_output: str,
    *,
    max_output_lines: int = _DEFAULT_TARGET_LINES,
    raw_log_path: str = "",
    exit_code: int = 0,
) -> DistilledLogResult:
    """Convenience helper invoking TerminalLogDistiller.distill."""
    return TerminalLogDistiller.distill(
        raw_output,
        max_output_lines=max_output_lines,
        raw_log_path=raw_log_path,
        exit_code=exit_code,
    )

