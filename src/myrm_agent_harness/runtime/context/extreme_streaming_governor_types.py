"""Type definitions for 384K Extreme Long Output Streaming and Chunk Memory Governor.

Defines schemas for incremental stream chunks, ring-buffer sliding retention,
automatic artifact offloading thresholds, and idempotent resume cursors.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- StreamChunkItem: A discrete incremental chunk emitted during long-running stream generation.
- StreamResumeCursor: Client resume cursor used for idempotent reconnect and gapless replay.
- OffloadStatus: State tracking for automatic large-text artifact offloading.
- StreamGovernorStats: Operational telemetry for extreme streaming buffers.

[POS]
Type definitions for 384K Extreme Long Output Streaming and Chunk Memory Governor.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StreamChunkItem:
    """A discrete incremental chunk emitted during long-running stream generation."""

    sequence_id: int
    byte_offset: int
    content: str
    char_length: int
    is_terminal: bool
    timestamp: float


@dataclass(frozen=True)
class StreamResumeCursor:
    """Client resume cursor used for idempotent reconnect and gapless replay."""

    stream_id: str
    last_acked_sequence_id: int
    last_acked_byte_offset: int


@dataclass(frozen=True)
class OffloadStatus:
    """State tracking for automatic large-text artifact offloading."""

    is_offloaded: bool
    artifact_id: str | None
    offload_byte_threshold: int
    total_bytes_streamed: int


@dataclass(frozen=True)
class StreamGovernorStats:
    """Operational telemetry for extreme streaming buffers."""

    stream_id: str
    total_chunks_produced: int
    total_chars_produced: int
    is_offloaded: bool
    artifact_id: str | None
    buffered_chunks_count: int
    evicted_chunks_count: int
    metadata: dict[str, str] = field(default_factory=dict)
