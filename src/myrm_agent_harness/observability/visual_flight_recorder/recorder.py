"""
[INPUT]: Visual frames, capture triggers, and configuration options.
[OUTPUT]: Thread-safe VisualFlightRecorder managing ring buffer and failure slice archive.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/visual_flight_recorder/recorder.py
"""

from collections import deque
import threading
import time
from typing import Deque, Dict, List, Optional
import uuid

from .models import FlightRecorderConfig, VisualFailureSlice, VisualFrame


class VisualFlightRecorder:
    """Ring-buffer in-memory flight recorder for agent browser and desktop visual telemetry."""

    def __init__(self, config: Optional[FlightRecorderConfig] = None) -> None:
        self._config = config or FlightRecorderConfig()
        self._lock = threading.Lock()
        self._buffer: Deque[VisualFrame] = deque(maxlen=self._config.max_frames)
        self._slices: Dict[str, VisualFailureSlice] = {}
        self._slice_order: List[str] = []
        self._max_stored_slices = 50

    @property
    def config(self) -> FlightRecorderConfig:
        return self._config

    def push_frame(self, frame: VisualFrame) -> None:
        """Append a newly captured visual frame to the rolling ring buffer."""
        with self._lock:
            self._buffer.append(frame)

    def current_buffer_size(self) -> int:
        """Return the number of frames currently in the rolling ring buffer."""
        with self._lock:
            return len(self._buffer)

    def detect_visual_stuck(self, min_sample_frames: int = 10) -> bool:
        """Detect if recent consecutive frames have identical or stagnant visual payloads."""
        with self._lock:
            if len(self._buffer) < min_sample_frames:
                return False

            recent_frames = list(self._buffer)[-min_sample_frames:]
            first_uri = recent_frames[0].image_data_uri
            identical_count = sum(1 for f in recent_frames if f.image_data_uri == first_uri)
            similarity_ratio = identical_count / float(min_sample_frames)
            return similarity_ratio >= self._config.stuck_detection_threshold

    def capture_failure_slice(
        self,
        trace_id: str,
        session_id: str,
        failure_kind: str,
        root_cause_label: str,
        animated_preview_uri: str = "",
        custom_slice_id: Optional[str] = None,
    ) -> VisualFailureSlice:
        """Seal current ring-buffer contents into an archived failure slice."""
        with self._lock:
            snapshot_frames = list(self._buffer)
            total_frames = len(snapshot_frames)

            duration_sec = 0.0
            if total_frames > 1:
                first_ts = snapshot_frames[0].timestamp_ms
                last_ts = snapshot_frames[-1].timestamp_ms
                duration_sec = max(0.0, (last_ts - first_ts) / 1000.0)

            slice_id = custom_slice_id or f"vslice-{uuid.uuid4().hex[:10]}"
            now_ms = int(time.time() * 1000)

            slice_record = VisualFailureSlice(
                slice_id=slice_id,
                trace_id=trace_id,
                session_id=session_id,
                failure_kind=failure_kind,
                root_cause_label=root_cause_label,
                total_frames=total_frames,
                duration_seconds=duration_sec,
                frames=snapshot_frames,
                animated_preview_uri=animated_preview_uri,
                created_at_ms=now_ms,
            )

            self._slices[slice_id] = slice_record
            self._slice_order.append(slice_id)

            # Evict older slices if capacity exceeded
            while len(self._slice_order) > self._max_stored_slices:
                oldest_id = self._slice_order.pop(0)
                self._slices.pop(oldest_id, None)

            return slice_record

    def get_slice(self, slice_id: str) -> Optional[VisualFailureSlice]:
        """Retrieve a specific failure slice by ID."""
        with self._lock:
            return self._slices.get(slice_id)

    def list_slices(
        self,
        session_id: Optional[str] = None,
        failure_kind: Optional[str] = None,
        limit: int = 20,
    ) -> List[VisualFailureSlice]:
        """List archived failure slices sorted newest-first with optional filtering."""
        with self._lock:
            results: List[VisualFailureSlice] = []
            for s_id in reversed(self._slice_order):
                item = self._slices.get(s_id)
                if not item:
                    continue
                if session_id and item.session_id != session_id:
                    continue
                if failure_kind and item.failure_kind != failure_kind:
                    continue
                results.append(item)
                if len(results) >= limit:
                    break
            return results

    def reset(self) -> None:
        """Clear current buffer and archived failure slices."""
        with self._lock:
            self._buffer.clear()
            self._slices.clear()
            self._slice_order.clear()


_DEFAULT_RECORDER: Optional[VisualFlightRecorder] = None
_INIT_LOCK = threading.Lock()


def get_default_visual_flight_recorder() -> VisualFlightRecorder:
    """Retrieve global thread-safe default VisualFlightRecorder instance."""
    global _DEFAULT_RECORDER
    if _DEFAULT_RECORDER is None:
        with _INIT_LOCK:
            if _DEFAULT_RECORDER is None:
                _DEFAULT_RECORDER = VisualFlightRecorder()
    return _DEFAULT_RECORDER
