"""Master suite for Checked Session Reply Stream Readers and Anti-Slop Governance.

Coordinates typed stream reader instances, batch frame ingestion pipelines,
cross-turn gap healing, and global streaming telemetry.
"""

from __future__ import annotations

from typing import Sequence

from .anti_slop_filter import AntiSlopFilter
from .checked_reply_reader import CheckedSessionReplyStreamReader
from .checked_stream_types import (
    AntiSlopFilterResult,
    AntiSlopViolationKind,
    StreamChunkFrame,
    StreamChunkKind,
    StreamReaderMetrics,
    StreamReaderState,
)


class CheckedSessionReplyStreamReadersAndAntiSlopGovernanceSuite:
    """Master suite governing checked streaming response ingestion and anti-slop quality controls."""

    def __init__(self) -> None:
        self._filter = AntiSlopFilter()
        self._active_readers: dict[str, CheckedSessionReplyStreamReader] = {}
        self._completed_metrics: list[StreamReaderMetrics] = []

    def create_reader(
        self,
        session_id: str,
        auto_heal_sequence_gaps: bool = True,
    ) -> CheckedSessionReplyStreamReader:
        """Instantiate and register a checked reply stream reader."""
        reader = CheckedSessionReplyStreamReader(
            session_id=session_id,
            auto_heal_sequence_gaps=auto_heal_sequence_gaps,
        )
        self._active_readers[session_id] = reader
        return reader

    def get_reader(self, session_id: str) -> CheckedSessionReplyStreamReader | None:
        """Retrieve an active stream reader by session id."""
        return self._active_readers.get(session_id)

    def process_stream(
        self,
        session_id: str,
        frames: Sequence[StreamChunkFrame],
        auto_heal: bool = True,
    ) -> tuple[str, StreamReaderMetrics, StreamReaderState]:
        """Convenience helper to feed a complete sequence of stream frames through a checked reader."""
        reader = self.create_reader(session_id=session_id, auto_heal_sequence_gaps=auto_heal)
        for frame in frames:
            reader.consume_frame(frame)

        final_metrics = reader.get_metrics()
        final_state = reader.state
        self._completed_metrics.append(final_metrics)

        return reader.get_full_buffered_content(), final_metrics, final_state

    def audit_content_for_slop(self, text: str) -> AntiSlopFilterResult:
        """Stand-alone audit of arbitrary text payloads for template tags and padding slop."""
        synthetic_frame = StreamChunkFrame(
            sequence_id=0,
            kind=StreamChunkKind.TEXT,
            content=text,
            session_id="audit",
        )
        return self._filter.filter_chunk(synthetic_frame)

    def get_global_telemetry(self) -> dict[str, int]:
        """Aggregate streaming reliability metrics across all processed readers."""
        total_processed = sum(m.frames_processed for m in self._completed_metrics)
        total_discarded = sum(m.frames_discarded for m in self._completed_metrics)
        total_healed = sum(m.healed_gaps for m in self._completed_metrics)
        total_chars = sum(m.total_characters_delivered for m in self._completed_metrics)

        return {
            "total_streams_completed": len(self._completed_metrics),
            "total_frames_processed": total_processed,
            "total_frames_discarded": total_discarded,
            "total_sequence_gaps_healed": total_healed,
            "total_characters_delivered": total_chars,
        }
