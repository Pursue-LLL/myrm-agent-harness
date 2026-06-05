"""Unified stream output processor for persistent sessions.

[OUTPUT]
StreamOutputProcessor: Handles auto-tee writing, SSE flood protection, and disk quota.

[POS]
Single source of truth for output handling: tee file writing with 50MB quota,
SSE 10FPS throttle, 500KB valve, and LRU log cleanup. Used by both
PersistentSession._execute_core and PersistentSession.execute_stream.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:

    class _AsyncWritable(Protocol):
        """Minimal protocol for an async file-like object with a write method."""

        async def write(self, data: str) -> int: ...


logger = logging.getLogger(__name__)

_TEE_MAX_BYTES = 50 * 1024 * 1024  # 50 MB hard limit
_TEE_KEEP_COUNT = 20  # LRU: keep the most recent N log files
_SSE_VALVE_BYTES = 500_000  # 500 KB: stop pushing SSE beyond this
_SSE_THROTTLE_INTERVAL = 0.1  # 10 FPS


class StreamOutputProcessor:
    """Unified output stream processor for tee writing and SSE throttling.

    Lifecycle:
      1. Call ``setup_tee(work_dir)`` once before the read loop.
      2. For every output chunk:
         a. ``write_tee(file, text)`` — writes to the tee log with quota.
         b. ``accumulate_sse(text)`` — returns text to emit when ready, or None.
      3. After the loop, call ``flush()`` to get any remaining buffered text.
    """

    def __init__(self) -> None:
        self._sse_acc_text = ""
        self._sse_bytes_sent = 0
        self._sse_warning_sent = False
        self._last_sse_time = time.monotonic()

        self._tee_bytes_written = 0
        self._tee_truncated = False
        self._tee_file_path: Path | None = None
        self._relative_tee_path: Path | str = ""

    @property
    def valve_triggered(self) -> bool:
        return self._sse_warning_sent

    @property
    def tee_truncated(self) -> bool:
        return self._tee_truncated

    @property
    def relative_tee_path(self) -> Path | str:
        return self._relative_tee_path

    @property
    def tee_file_path(self) -> Path | None:
        return self._tee_file_path

    def setup_tee(self, work_dir: str) -> Path:
        """Prepare tee directory and file path. Returns the tee file path.

        Also performs LRU cleanup of old log files.
        """
        tee_dir = Path(work_dir) / ".myrm" / "tee"
        tee_dir.mkdir(parents=True, exist_ok=True)

        try:
            log_files = sorted(tee_dir.glob("cmd_*.log"), key=lambda p: p.stat().st_mtime)
            if len(log_files) > _TEE_KEEP_COUNT:
                for f in log_files[:-_TEE_KEEP_COUNT]:
                    f.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Failed to cleanup tee logs: {e}")

        tee_file_name = f"cmd_{uuid.uuid4().hex[:8]}.log"
        self._tee_file_path = tee_dir / tee_file_name
        try:
            self._relative_tee_path = self._tee_file_path.relative_to(Path(work_dir))
        except ValueError:
            self._relative_tee_path = self._tee_file_path

        return self._tee_file_path

    async def write_tee(self, tee_file: _AsyncWritable, text: str) -> None:
        """Write a chunk to the tee file, respecting disk quota."""
        if self._tee_truncated:
            return

        chunk_bytes_len = len(text.encode("utf-8", errors="replace"))
        if self._tee_bytes_written + chunk_bytes_len > _TEE_MAX_BYTES:
            allowed_bytes = _TEE_MAX_BYTES - self._tee_bytes_written
            if allowed_bytes > 0:
                encoded = text.encode("utf-8", errors="replace")[:allowed_bytes]
                await tee_file.write(encoded.decode("utf-8", errors="ignore"))
            await tee_file.write("\n\n[System Warning: Tee log file exceeded 50MB hard limit and was truncated.]\n")
            self._tee_truncated = True
        else:
            await tee_file.write(text)
            self._tee_bytes_written += chunk_bytes_len

    def accumulate_sse(self, text: str) -> str | None:
        """Accumulate text for SSE emission. Returns text to send, or None.

        Returns:
            - The accumulated text to emit (when throttle interval has passed)
            - ``None`` when still accumulating (not yet time to emit)

        Once the valve triggers (>500KB), always returns ``None``.
        """
        self._sse_acc_text += text
        self._sse_bytes_sent += len(text.encode("utf-8", errors="replace"))

        if self._sse_bytes_sent > _SSE_VALVE_BYTES:
            if not self._sse_warning_sent:
                self._sse_warning_sent = True
                return self._build_valve_warning()
            return None

        now = time.monotonic()
        if now - self._last_sse_time >= _SSE_THROTTLE_INTERVAL:
            result = self._sse_acc_text
            self._sse_acc_text = ""
            self._last_sse_time = now
            return result

        return None

    def flush(self) -> str:
        """Return any remaining buffered SSE text. Call after the read loop."""
        if self._sse_warning_sent:
            return ""
        result = self._sse_acc_text
        self._sse_acc_text = ""
        return result

    def _build_valve_warning(self) -> str:
        limit_note = (
            " (Note: The log file itself reached the 50MB physical limit and was also truncated.)"
            if self._tee_truncated
            else ""
        )
        return (
            f"\n\n[System Warning: Terminal stream suspended to prevent UI freeze. "
            f"Command is still running in background. The FULL original output is "
            f"being stream-saved to `{self._relative_tee_path}`{limit_note}.]\n\n"
        )

    def build_truncation_system_note(self) -> str:
        """Build the system note appended to stdout when output was truncated."""
        limit_note = (
            " (Note: The log file itself reached the 50MB physical limit and was also truncated.)"
            if self._tee_truncated
            else ""
        )
        return (
            f"\n\n[System Note: Output was truncated. The FULL original output "
            f"was stream-saved to `{self._relative_tee_path}`{limit_note}. "
            f"Use file_read_tool to read specific sections "
            f"(e.g. {self._relative_tee_path}:100-200 for line ranges).]"
        )
