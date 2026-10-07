"""Checked Session Reply Stream Reader implementing sequential integrity and resilient state transitions.

Monitors frame continuity, heals sequencing gaps, purges empty or invalid slop chunks,
and maintains robust streaming state boundaries across client-server pipelines.
"""

from __future__ import annotations

from typing import Sequence

from .anti_slop_filter import AntiSlopFilter
from .checked_stream_types import (
    AntiSlopViolationKind,
    StreamChunkFrame,
    StreamChunkKind,
    StreamReaderMetrics,
    StreamReaderState,
)


class CheckedSessionReplyStreamReader:
    """Stateful stream reader validating frame sequence continuity and anti-slop hygiene."""

    def __init__(self, session_id: str, auto_heal_sequence_gaps: bool = True) -> None:
        self._session_id = session_id
        self._auto_heal_gaps = auto_heal_sequence_gaps
        self._state = StreamReaderState.IDLE
        self._expected_sequence_id = 0

        self._filter = AntiSlopFilter()
        self._frames_processed = 0
        self._frames_discarded = 0
        self._healed_gaps = 0
        self._total_characters = 0
        self._violation_counts: dict[str, int] = {}
        self._buffer: list[str] = []

    @property
    def session_id(self) -> str:
        """Active session identifier."""
        return self._session_id

    @property
    def state(self) -> StreamReaderState:
        """Current reader state machine lifecycle phase."""
        return self._state

    @property
    def expected_sequence_id(self) -> int:
        """Expected next sequence index."""
        return self._expected_sequence_id

    def consume_frame(self, frame: StreamChunkFrame) -> StreamChunkFrame | None:
        """Ingest, validate, heal, and sanitize a stream frame.

        Returns the sanitized frame if valid and accepted, or None if dropped as invalid slop.
        """
        self._frames_processed += 1

        # 1. State transition from IDLE to STREAMING upon first incoming frame
        if self._state == StreamReaderState.IDLE:
            self._state = StreamReaderState.STREAMING

        # Terminal state guard: cannot consume if broken or completed
        if self._state in (StreamReaderState.BROKEN, StreamReaderState.COMPLETED):
            self._frames_discarded += 1
            return None

        # 2. Sequence gap detection and healing
        if frame.sequence_id != self._expected_sequence_id:
            if self._auto_heal_gaps:
                self._state = StreamReaderState.HEALING
                self._healed_gaps += 1
                # Auto-align expected sequence to after the current frame
                self._expected_sequence_id = frame.sequence_id + 1
                self._state = StreamReaderState.STREAMING
            else:
                self._state = StreamReaderState.BROKEN
                self._frames_discarded += 1
                return None
        else:
            self._expected_sequence_id += 1

        # 3. Handle explicit DONE frame
        if frame.kind == StreamChunkKind.DONE:
            self._state = StreamReaderState.COMPLETED
            return frame

        # 4. Handle ERROR frame
        if frame.kind == StreamChunkKind.ERROR:
            self._state = StreamReaderState.BROKEN
            return frame

        # 5. Anti-slop quality filtering
        filter_result = self._filter.filter_chunk(frame)
        for viol in filter_result.violations:
            self._violation_counts[viol.value] = self._violation_counts.get(viol.value, 0) + 1

        if not filter_result.is_valid:
            self._frames_discarded += 1
            return None

        # Deliver sanitized frame
        sanitized_frame = StreamChunkFrame(
            sequence_id=frame.sequence_id,
            kind=frame.kind,
            content=filter_result.cleaned_content,
            session_id=frame.session_id,
            timestamp_ms=frame.timestamp_ms,
            is_synthesized=frame.is_synthesized,
        )

        self._total_characters += len(sanitized_frame.content)
        self._buffer.append(sanitized_frame.content)
        return sanitized_frame

    def get_full_buffered_content(self) -> str:
        """Combine all successfully read chunk contents into a consolidated response."""
        return "".join(self._buffer)

    def get_metrics(self) -> StreamReaderMetrics:
        """Produce point-in-time streaming health telemetry."""
        return StreamReaderMetrics(
            frames_processed=self._frames_processed,
            frames_discarded=self._frames_discarded,
            healed_gaps=self._healed_gaps,
            total_characters_delivered=self._total_characters,
            violations_detected=dict(self._violation_counts),
        )
