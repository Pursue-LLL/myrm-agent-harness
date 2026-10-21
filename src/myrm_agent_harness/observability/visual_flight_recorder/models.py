"""
[INPUT]: Raw visual capture frames, buffer configuration, and failure/stuck state parameters.
[OUTPUT]: Immutable Pydantic models for ring-buffer visual flight recorder and failure slice playback.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/visual_flight_recorder/models.py
"""

from typing import List
from pydantic import BaseModel, Field


class VisualFrame(BaseModel):
    """Single visual frame captured from headless browser or virtual desktop."""

    frame_index: int = Field(..., ge=0, description="Sequential frame index")
    timestamp_ms: int = Field(..., ge=0, description="Epoch timestamp of capture")
    image_data_uri: str = Field(..., description="Data URI or local resource URI of the frame image")
    width: int = Field(default=1280, ge=1, description="Frame width in pixels")
    height: int = Field(default=720, ge=1, description="Frame height in pixels")
    dom_event_summary: str = Field(default="", description="DOM or input event occurred during frame")


class FlightRecorderConfig(BaseModel):
    """Configuration for rolling ring-buffer visual flight recorder."""

    max_frames: int = Field(default=75, ge=5, le=300, description="Maximum rolling frames in ring buffer (75 @ 5fps = 15s)")
    target_fps: float = Field(default=5.0, gt=0.0, description="Target capture frequency in frames per second")
    buffer_window_seconds: float = Field(default=15.0, gt=0.0, description="Rolling time window in seconds")
    stuck_detection_threshold: float = Field(default=0.95, ge=0.5, le=1.0, description="Similarity ratio to declare stuck state")


class VisualFailureSlice(BaseModel):
    """Archived visual failure slice extracted from the ring buffer upon crash or stuck state."""

    slice_id: str = Field(..., description="Unique failure slice identifier")
    trace_id: str = Field(..., description="Correlated execution trace ID")
    session_id: str = Field(..., description="Correlated session identifier")
    failure_kind: str = Field(..., description="Failure category: popup_overlay, captcha_slider, element_timeout, stuck_loop, crash")
    root_cause_label: str = Field(..., description="Actionable human-readable root cause explanation")
    total_frames: int = Field(..., ge=0, description="Count of frames in this slice")
    duration_seconds: float = Field(..., ge=0.0, description="Total duration of visual replay")
    frames: List[VisualFrame] = Field(default_factory=list, description="Ordered frames for filmstrip and animation replay")
    animated_preview_uri: str = Field(default="", description="Optional URI to stitched WebP/GIF animation")
    created_at_ms: int = Field(..., ge=0, description="Epoch timestamp when failure slice was sealed")
