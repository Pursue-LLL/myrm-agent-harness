"""Streaming buffer for persistent sessions.

Prevents OOM on huge outputs, guarantees bounded memory footprint,
and provides live chunks for SSE UI updates.

[POS]
Efficient byte stream buffer. Supports zero-copy boundary detection and memory-bounded head/tail retention.
"""

from __future__ import annotations

import codecs
from collections import deque

from myrm_agent_harness.toolkits.code_execution.executors.common.executor_utils import MAX_OUTPUT_CHARS


class ExecutionStreamBuffer:
    """A memory-efficient stream buffer with bounded footprint and marker detection."""

    def __init__(self, max_chars: int = MAX_OUTPUT_CHARS, head_ratio: float = 0.3):
        self._max_chars = max_chars
        self._head_limit = int(max_chars * head_ratio)
        self._tail_limit = max_chars - self._head_limit

        self._head_buf: list[str] = []
        self._head_len = 0
        self._tail_buf: deque[str] = deque()
        self._tail_len = 0

        self._total_chars_seen = 0
        self._is_truncated = False

        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._byte_buf = bytearray()

        self.done = False
        self.exit_code = 1

    def process_bytes(self, chunk: bytes, exit_marker: str, end_marker: str) -> str:
        """Process binary chunk, detecting markers and returning safe text.

        Uses bytelevel search for markers to avoid premature decoding overhead.
        """
        if self.done:
            return ""

        self._byte_buf.extend(chunk)

        exit_m_bytes = exit_marker.encode("ascii")
        end_m_bytes = end_marker.encode("ascii")

        idx_exit = self._byte_buf.find(exit_m_bytes)
        if idx_exit != -1:
            idx_end = self._byte_buf.find(end_m_bytes, idx_exit + len(exit_m_bytes))
            if idx_end != -1:
                # Both markers found
                safe_bytes = self._byte_buf[:idx_exit]
                exit_code_bytes = self._byte_buf[idx_exit + len(exit_m_bytes) : idx_end]

                try:
                    self.exit_code = int(exit_code_bytes.strip())
                except (ValueError, TypeError) as e:
                    import logging

                    logging.getLogger(__name__).error(f"Failed to parse exit code from {exit_code_bytes!r}: {e}")
                    self.exit_code = 1

                safe_text = self._decoder.decode(safe_bytes, final=True)
                self.done = True
                self._byte_buf.clear()
                self._append_to_buffers(safe_text)
                return safe_text

        # Optimization: Return safe text that definitely does not contain a partial marker
        lookback = max(len(exit_m_bytes), len(end_m_bytes)) + 8
        limit = len(self._byte_buf) - lookback

        # We must NOT consume the exit marker if it's partially or fully present
        if idx_exit != -1:
            limit = min(limit, idx_exit)

        if limit > 0:
            safe_len = limit
            # Ensure we don't split in the middle of a multi-byte UTF-8 char
            while safe_len > 0 and (self._byte_buf[safe_len] & 0xC0) == 0x80:
                safe_len -= 1

            if safe_len > 0:
                safe_bytes = self._byte_buf[:safe_len]
                del self._byte_buf[:safe_len]
                safe_text = self._decoder.decode(safe_bytes)
                self._append_to_buffers(safe_text)
                return safe_text

        return ""

    def _append_to_buffers(self, text: str) -> None:
        if not text:
            return

        t_len = len(text)
        self._total_chars_seen += t_len

        # Fill head
        if self._head_len < self._head_limit:
            available = self._head_limit - self._head_len
            part = text[:available]
            self._head_buf.append(part)
            self._head_len += len(part)
            text = text[available:]
            if not text:
                return

        # Fill tail (Ring Buffer)
        self._is_truncated = True
        self._tail_buf.append(text)
        self._tail_len += len(text)

        while self._tail_len > self._tail_limit and self._tail_buf:
            oldest = self._tail_buf.popleft()
            self._tail_len -= len(oldest)
            if self._tail_len < self._tail_limit:
                extra = self._tail_limit - self._tail_len
                if extra > 0:
                    self._tail_buf.appendleft(oldest[-extra:])
                    self._tail_len += extra

    def get_final_output(self) -> str:
        """Construct the final result with logical truncation awareness."""
        if self._byte_buf:
            # Last attempt decode remaining bytes
            suffix = self._decoder.decode(self._byte_buf, final=True)
            self._append_to_buffers(suffix)
            self._byte_buf.clear()

        head = "".join(self._head_buf)
        if not self._is_truncated:
            return head

        tail = "".join(self._tail_buf)
        dropped = self._total_chars_seen - (len(head) + len(tail))
        warning = f"\n\n[System Warning: The middle {dropped} characters of output were truncated to prevent memory overflow]\n\n"
        return head + warning + tail
