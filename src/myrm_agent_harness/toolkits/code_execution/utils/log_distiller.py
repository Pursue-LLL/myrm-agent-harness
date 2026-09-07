"""High-signal terminal log distiller for long-running build, execution, and deployment tasks.

Cleanses high-frequency rolling progress animations, dynamic ANSI sequences,
extracts high-signal error/panic/HTTP failure anchors with surrounding context,
and formats high-density diagnostic summaries for LLM context optimization.

[INPUT]
- str: raw terminal stdout/stderr stream.
- int | None: process exit code.
- str: absolute or relative path to persistent tee log on disk.

[OUTPUT]
- DistilledLogResult: Typed container with compression statistics and distilled text.
- TerminalLogDistiller: Thread-safe log distillation engine.

[POS]
Execution layer utility for myrm_agent_harness.toolkits.code_execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from myrm_agent_harness.utils.text_utils import strip_ansi

# Patterns indicating transient, repetitive, or low-information progress updates
_PROGRESS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*\[\s*\d+%\s*\]", re.IGNORECASE),
    re.compile(r"^\s*\d+%\s*\[=+>?\s*\]", re.IGNORECASE),
    re.compile(r"^\s*fetching:\s*\d+%", re.IGNORECASE),
    re.compile(r"^\s*downloading:\s*\d+%", re.IGNORECASE),
    re.compile(r"^\s*extracting:\s*\d+%", re.IGNORECASE),
    re.compile(r"^\s*progress:\s*\[[\s=>#-]+\]", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:kB|MB|GB|B)/s\b", re.IGNORECASE),
    re.compile(r"^\s*(?:[-|\\/]\s*)?(?:resolving|downloading|unpacking)\s+packages\b", re.IGNORECASE),
    re.compile(r"^\s*░+\s*\d+%", re.IGNORECASE),
)

# High-signal error and operational failure patterns
_ERROR_ANCHOR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("HTTP_403_FORBIDDEN", re.compile(r"\b403\s+Forbidden\b|trustedHosts", re.IGNORECASE)),
    ("HTTP_426_UPGRADE_REQUIRED", re.compile(r"\b426\s+Upgrade\s+Required\b", re.IGNORECASE)),
    ("HTTP_401_UNAUTHORIZED", re.compile(r"\b401\s+Unauthorized\b", re.IGNORECASE)),
    ("HTTP_502_BAD_GATEWAY", re.compile(r"\b502\s+Bad\s+Gateway\b", re.IGNORECASE)),
    ("SOCKET_EADDRINUSE", re.compile(r"\bEADDRINUSE\b|address\s+already\s+in\s+use\b", re.IGNORECASE)),
    ("SOCKET_ECONNREFUSED", re.compile(r"\bECONNREFUSED\b|connection\s+refused\b", re.IGNORECASE)),
    ("NETWORK_TIMEOUT", re.compile(r"\bETIMEDOUT\b|network\s+timeout\b|connect\s+timeout\b", re.IGNORECASE)),
    ("PYTHON_TRACEBACK", re.compile(r"^Traceback\s+\(most\s+recent\s+call\s+last\):", re.IGNORECASE)),
    ("NPM_ERROR", re.compile(r"^npm\s+ERR!\b", re.IGNORECASE)),
    ("RUST_COMPILER_ERROR", re.compile(r"^error\[E\d+\]:\b", re.IGNORECASE)),
    ("FATAL_PANIC", re.compile(r"\b(?:FATAL|PANIC|Segmentation\s+fault|core\s+dumped)\b", re.IGNORECASE)),
    ("PERMISSION_DENIED", re.compile(r"\bPermission\s+denied\b|\bAccess\s+denied\b", re.IGNORECASE)),
    ("MODULE_NOT_FOUND", re.compile(r"\b(?:ModuleNotFoundError|Cannot\s+find\s+module)\b", re.IGNORECASE)),
    ("COMMAND_NOT_FOUND", re.compile(r"\b(?:command\s+not\s+found|not\s+recognized\s+as\s+an\s+internal)\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class DistilledLogResult:
    """Result envelope of terminal log distillation."""

    raw_line_count: int
    distilled_line_count: int
    compression_ratio: float
    distilled_text: str
    extracted_error_signals: list[str]
    exit_code: int | None = None
    raw_log_path: str = ""
    is_passthrough: bool = False


class TerminalLogDistiller:
    """High-performance thread-safe log cleanser and contextual error extractor."""

    def __init__(self, *, default_max_lines: int = 50, passthrough_threshold_lines: int = 80) -> None:
        self._default_max_lines = default_max_lines
        self._passthrough_threshold_lines = passthrough_threshold_lines

    def distill(
        self,
        raw_output: str,
        *,
        exit_code: int | None = None,
        raw_log_path: str = "",
        max_lines: int | None = None,
    ) -> DistilledLogResult:
        """Distill raw terminal output stream into concise, high-signal diagnostics.

        Args:
            raw_output: Raw stdout/stderr string from terminal or subprocess.
            exit_code: Optional process exit code.
            raw_log_path: Path to the on-disk raw tee log file.
            max_lines: Maximum lines to retain in distilled output.

        Returns:
            DistilledLogResult with compression stats and distilled text.
        """
        target_max_lines = max_lines if max_lines is not None else self._default_max_lines
        clean_text = strip_ansi(raw_output or "")
        lines = [line.strip("\r") for line in clean_text.splitlines()]
        raw_line_count = len(lines)

        # 1. Short output safety passthrough
        if raw_line_count <= self._passthrough_threshold_lines:
            error_signals = self._detect_signals(lines)
            return DistilledLogResult(
                raw_line_count=raw_line_count,
                distilled_line_count=raw_line_count,
                compression_ratio=0.0,
                distilled_text=clean_text,
                extracted_error_signals=error_signals,
                exit_code=exit_code,
                raw_log_path=raw_log_path,
                is_passthrough=True,
            )

        # 2. Filter transient progress/churn lines
        filtered_lines: list[tuple[int, str]] = []
        for idx, line in enumerate(lines):
            if not self._is_progress_line(line):
                filtered_lines.append((idx, line))

        # 3. Identify error anchor line indices
        anchor_indices: set[int] = set()
        detected_signals: list[str] = []
        for orig_idx, line in filtered_lines:
            for signal_name, pattern in _ERROR_ANCHOR_PATTERNS:
                if pattern.search(line):
                    anchor_indices.add(orig_idx)
                    if signal_name not in detected_signals:
                        detected_signals.append(signal_name)

        # 4. Expand context around anchor indices (3 lines before & after)
        selected_line_indices: set[int] = set()
        for anchor in anchor_indices:
            start_bound = max(0, anchor - 3)
            end_bound = min(raw_line_count - 1, anchor + 3)
            for i in range(start_bound, end_bound + 1):
                selected_line_indices.add(i)

        # 5. Retain recent tail context (last 25 lines)
        tail_start = max(0, raw_line_count - 25)
        for i in range(tail_start, raw_line_count):
            selected_line_indices.add(i)

        # 6. Retain top head context (first 5 lines)
        for i in range(min(5, raw_line_count)):
            selected_line_indices.add(i)

        # 7. Assemble distilled content with omission markers
        sorted_indices = sorted(selected_line_indices)
        distilled_lines: list[str] = []
        last_idx = -1

        for idx in sorted_indices:
            if last_idx != -1 and idx > last_idx + 1:
                omitted_count = idx - last_idx - 1
                distilled_lines.append(f"... [omitted {omitted_count} lines of progress/logs] ...")
            distilled_lines.append(lines[idx])
            last_idx = idx

        # 8. Cap lines if still exceeding target_max_lines
        if len(distilled_lines) > target_max_lines:
            head_part = distilled_lines[: target_max_lines // 2]
            tail_part = distilled_lines[-(target_max_lines // 2) :]
            distilled_lines = head_part + ["... [truncated for token efficiency] ..."] + tail_part

        distilled_text_body = "\n".join(distilled_lines)

        # 9. Format structured banner for LLM consumption
        header_parts = [
            f"[DISTILLED LOG: {raw_line_count} lines -> {len(distilled_lines)} lines",
        ]
        if detected_signals:
            header_parts.append(f"signals: {','.join(detected_signals)}")
        if raw_log_path:
            header_parts.append(f"raw_log: {raw_log_path}")
        if exit_code is not None:
            header_parts.append(f"exit_code: {exit_code}")
        header_banner = " | ".join(header_parts) + "]"

        final_distilled_text = f"{header_banner}\n{distilled_text_body}"
        compression_ratio = round(1.0 - (len(distilled_lines) / max(1, raw_line_count)), 4)

        return DistilledLogResult(
            raw_line_count=raw_line_count,
            distilled_line_count=len(distilled_lines),
            compression_ratio=compression_ratio,
            distilled_text=final_distilled_text,
            extracted_error_signals=detected_signals,
            exit_code=exit_code,
            raw_log_path=raw_log_path,
            is_passthrough=False,
        )

    def _is_progress_line(self, line: str) -> bool:
        """Check if line matches transient progress bar patterns."""
        if not line:
            return False
        for pattern in _PROGRESS_PATTERNS:
            if pattern.search(line):
                return True
        return False

    def _detect_signals(self, lines: list[str]) -> list[str]:
        """Scan line list for matching error signal labels."""
        signals: list[str] = []
        for line in lines:
            for signal_name, pattern in _ERROR_ANCHOR_PATTERNS:
                if pattern.search(line) and signal_name not in signals:
                    signals.append(signal_name)
        return signals
