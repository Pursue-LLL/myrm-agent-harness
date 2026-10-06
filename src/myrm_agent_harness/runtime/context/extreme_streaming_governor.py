"""384K Extreme Long Output Streaming and Chunk Memory Governor.

Manages ring-buffered incremental chunks for massive token streams,
performs automatic threshold-based artifact offloading (>32KB) to protect DOM memory,
and supports idempotent reconnect resume based on sequence IDs and byte offsets.
"""

from __future__ import annotations

import time
from collections import deque
from threading import RLock

from myrm_agent_harness.runtime.context.extreme_streaming_governor_types import (
    OffloadStatus,
    StreamChunkItem,
    StreamGovernorStats,
    StreamResumeCursor,
)

__all__ = [
    "CursorExpiredError",
    "ExtremeStreamingGovernor",
    "OffloadStatus",
    "StreamChunkItem",
    "StreamGovernorStats",
    "StreamResumeCursor",
]


class CursorExpiredError(Exception):
    """Raised when the requested resume cursor has fallen outside the ring buffer window."""


class ExtremeStreamingGovernor:
    """Controls high-volume streaming throughput with bounded memory and offloading."""

    def __init__(
        self,
        stream_id: str,
        buffer_capacity: int = 2000,
        offload_byte_threshold: int = 32768,
        artifact_id_prefix: str = "art-stream",
    ) -> None:
        self._stream_id = stream_id
        self._buffer_capacity = buffer_capacity
        self._offload_byte_threshold = offload_byte_threshold
        self._artifact_id_prefix = artifact_id_prefix

        self._lock = RLock()
        self._ring_buffer: deque[StreamChunkItem] = deque(maxlen=buffer_capacity)
        self._next_sequence_id: int = 0
        self._accumulated_bytes: int = 0
        self._accumulated_chars: int = 0
        self._evicted_chunks_count: int = 0
        self._is_offloaded: bool = False
        self._artifact_id: str | None = None
        self._full_content_segments: list[str] = []

    @property
    def stream_id(self) -> str:
        return self._stream_id

    @property
    def is_offloaded(self) -> bool:
        with self._lock:
            return self._is_offloaded

    @property
    def artifact_id(self) -> str | None:
        with self._lock:
            return self._artifact_id

    def push_chunk(self, content: str, is_terminal: bool = False) -> StreamChunkItem:
        """Pushes an incremental streaming delta, evaluates offloading, and retains in ring buffer."""
        chunk_bytes = len(content.encode("utf-8"))
        chunk_chars = len(content)
        now = time.time()

        with self._lock:
            seq_id = self._next_sequence_id
            byte_offset = self._accumulated_bytes

            # Check if ring buffer is at capacity before appending
            if len(self._ring_buffer) == self._buffer_capacity:
                self._evicted_chunks_count += 1

            item = StreamChunkItem(
                sequence_id=seq_id,
                byte_offset=byte_offset,
                content=content,
                char_length=chunk_chars,
                is_terminal=is_terminal,
                timestamp=now,
            )

            self._ring_buffer.append(item)
            self._full_content_segments.append(content)
            self._next_sequence_id += 1
            self._accumulated_bytes += chunk_bytes
            self._accumulated_chars += chunk_chars

            # Evaluate automatic offload threshold
            if not self._is_offloaded and self._accumulated_bytes >= self._offload_byte_threshold:
                self._is_offloaded = True
                self._artifact_id = f"{self._artifact_id_prefix}-{self._stream_id}"

            return item

    def get_chunks_since(self, cursor: StreamResumeCursor) -> tuple[StreamChunkItem, ...]:
        """Provides idempotent replay for reconnecting clients based on sequence IDs."""
        if cursor.stream_id != self._stream_id:
            raise ValueError(
                f"Cursor stream_id '{cursor.stream_id}' does not match governor '{self._stream_id}'."
            )

        with self._lock:
            if not self._ring_buffer:
                return ()

            oldest_available_seq = self._ring_buffer[0].sequence_id
            if cursor.last_acked_sequence_id < oldest_available_seq - 1:
                raise CursorExpiredError(
                    f"Requested sequence {cursor.last_acked_sequence_id} expired. "
                    f"Oldest retained sequence is {oldest_available_seq}."
                )

            replayed: list[StreamChunkItem] = [
                item
                for item in self._ring_buffer
                if item.sequence_id > cursor.last_acked_sequence_id
            ]
            return tuple(replayed)

    def get_lightweight_summary(self, preview_chars: int = 500) -> str:
        """Generates a DOM-safe summary when stream has been offloaded to artifact view."""
        with self._lock:
            full_text = "".join(self._full_content_segments)
            if not self._is_offloaded or len(full_text) <= preview_chars:
                return full_text

            preview = full_text[:preview_chars]
            return (
                f"{preview}\n\n"
                f"[... Output stream offloaded to Artifact '{self._artifact_id}' "
                f"({self._accumulated_chars} chars, {self._accumulated_bytes} bytes) ...]"
            )

    def get_offload_status(self) -> OffloadStatus:
        """Reports the current artifact offload state."""
        with self._lock:
            return OffloadStatus(
                is_offloaded=self._is_offloaded,
                artifact_id=self._artifact_id,
                offload_byte_threshold=self._offload_byte_threshold,
                total_bytes_streamed=self._accumulated_bytes,
            )

    def get_governor_stats(self) -> StreamGovernorStats:
        """Captures telemetry statistics for operational monitoring."""
        with self._lock:
            return StreamGovernorStats(
                stream_id=self._stream_id,
                total_chunks_produced=self._next_sequence_id,
                total_chars_produced=self._accumulated_chars,
                is_offloaded=self._is_offloaded,
                artifact_id=self._artifact_id,
                buffered_chunks_count=len(self._ring_buffer),
                evicted_chunks_count=self._evicted_chunks_count,
            )
