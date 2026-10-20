"""Torn tail detection and self-repair engine for append-only event logs.

An unterminated final line is an uncommitted append resulting from a system crash,
sudden power loss, or process termination. It is skipped on read and truncated
before the next append -- never newline-completed and never surfaced to a consumer
whose next append destroys it.

[INPUT]
- pathlib.Path: File path to inspect or repair

[OUTPUT]
- TailInspectionResult: Detailed inspection metadata
- TailRepairReport: Self-repair execution report
- TailRepairError: Propagated error on repair failure
- inspect_tail: O(1) reverse seek tail verification
- repair_torn_tail: Atomic truncation to clean newline boundary
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PROBE_BUFFER_SIZE: int = 4096


class TailRepairError(RuntimeError):
    """Raised when tail repair fails and must propagate to the caller."""


@dataclass(frozen=True, slots=True)
class TailInspectionResult:
    """Outcome of inspecting the tail of an event log file."""

    file_size: int
    clean_size: int
    has_torn_tail: bool
    torn_bytes: int


@dataclass(frozen=True, slots=True)
class TailRepairReport:
    """Report detailing self-repair actions performed on an event log file."""

    path: Path
    repaired: bool
    truncated_bytes: int
    original_size: int
    repaired_size: int


def inspect_tail(file_path: Path, probe_buffer_size: int = _DEFAULT_PROBE_BUFFER_SIZE) -> TailInspectionResult:
    """Inspect the end of an event log file to detect any unterminated final line.

    Performs an O(1) reverse seek inspection:
    - If the last byte is b'\\n', returns immediately with has_torn_tail=False.
    - If the file is empty or missing, returns clean state.
    - If the last byte is not b'\\n', scans backwards to locate the last b'\\n' offset.

    Args:
        file_path: Path to the log file.
        probe_buffer_size: Chunk size when scanning backwards for previous newline.

    Returns:
        TailInspectionResult with file_size, clean_size, has_torn_tail, and torn_bytes.
    """
    try:
        with file_path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            if file_size == 0:
                return TailInspectionResult(
                    file_size=0,
                    clean_size=0,
                    has_torn_tail=False,
                    torn_bytes=0,
                )

            # O(1) fast-path check on the final byte
            f.seek(file_size - 1, os.SEEK_SET)
            last_byte = f.read(1)
            if last_byte == b"\n":
                return TailInspectionResult(
                    file_size=file_size,
                    clean_size=file_size,
                    has_torn_tail=False,
                    torn_bytes=0,
                )

            # Unterminated final line detected: reverse scan to find the last valid newline
            clean_offset: int = 0
            current_end: int = file_size
            while current_end > 0:
                read_len = min(probe_buffer_size, current_end)
                start_offset = current_end - read_len
                f.seek(start_offset, os.SEEK_SET)
                chunk = f.read(read_len)
                rpos = chunk.rfind(b"\n")
                if rpos != -1:
                    clean_offset = start_offset + rpos + 1
                    break
                current_end = start_offset

            torn_bytes = file_size - clean_offset
            return TailInspectionResult(
                file_size=file_size,
                clean_size=clean_offset,
                has_torn_tail=True,
                torn_bytes=torn_bytes,
            )
    except FileNotFoundError:
        return TailInspectionResult(
            file_size=0,
            clean_size=0,
            has_torn_tail=False,
            torn_bytes=0,
        )


def repair_torn_tail(file_path: Path) -> TailRepairReport:
    """Atomically truncate an unterminated final line before any new append occurs.

    Never newline-completes an uncommitted line. Truncates the file back to the
    last valid newline boundary and forces an fsync. Propagates failures as TailRepairError.

    Args:
        file_path: Path to the log file to repair.

    Returns:
        TailRepairReport summarizing repair outcome.

    Raises:
        TailRepairError: If file truncation or sync fails.
    """
    try:
        inspection = inspect_tail(file_path)
    except OSError as exc:
        raise TailRepairError(
            f"Failed to inspect event log tail {file_path}: {exc}"
        ) from exc

    if not inspection.has_torn_tail:
        return TailRepairReport(
            path=file_path,
            repaired=False,
            truncated_bytes=0,
            original_size=inspection.file_size,
            repaired_size=inspection.file_size,
        )

    logger.warning(
        "Torn tail detected in event log %s: file_size=%d clean_size=%d torn_bytes=%d; truncating uncommitted tail",
        file_path,
        inspection.file_size,
        inspection.clean_size,
        inspection.torn_bytes,
    )

    try:
        with file_path.open("r+b") as f:
            f.truncate(inspection.clean_size)
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        raise TailRepairError(
            f"Failed to truncate torn tail from event log {file_path} "
            f"(target clean_size={inspection.clean_size}): {exc}"
        ) from exc

    return TailRepairReport(
        path=file_path,
        repaired=True,
        truncated_bytes=inspection.torn_bytes,
        original_size=inspection.file_size,
        repaired_size=inspection.clean_size,
    )
