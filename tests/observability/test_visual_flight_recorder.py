"""
[INPUT]: visual_flight_recorder models and recorder.
[OUTPUT]: Pytest verification for ring-buffer VisualFlightRecorder and failure slice capture.
[POS]: myrm-agent-harness/tests/observability/test_visual_flight_recorder.py
"""

import pytest

from myrm_agent_harness.observability.visual_flight_recorder import (
    FlightRecorderConfig,
    VisualFailureSlice,
    VisualFlightRecorder,
    VisualFrame,
    get_default_visual_flight_recorder,
)


def test_ring_buffer_rolling_and_capacity() -> None:
    # Set capacity to 5 frames for quick testing
    cfg = FlightRecorderConfig(max_frames=5, target_fps=5.0, buffer_window_seconds=1.0)
    recorder = VisualFlightRecorder(config=cfg)

    assert recorder.current_buffer_size() == 0

    for i in range(8):
        frame = VisualFrame(
            frame_index=i,
            timestamp_ms=1700000000000 + i * 200,
            image_data_uri=f"data:image/png;base64,frame_{i}",
            dom_event_summary=f"click_btn_{i}",
        )
        recorder.push_frame(frame)

    # Deque must hold exactly max_frames (5), with the latest frames (3, 4, 5, 6, 7)
    assert recorder.current_buffer_size() == 5

    slice_rec = recorder.capture_failure_slice(
        trace_id="trace-test-1",
        session_id="sess-test-1",
        failure_kind="element_timeout",
        root_cause_label="Timeout waiting for submit button selector #pay-btn",
    )

    assert slice_rec.total_frames == 5
    assert slice_rec.frames[0].frame_index == 3
    assert slice_rec.frames[-1].frame_index == 7
    assert slice_rec.failure_kind == "element_timeout"
    assert slice_rec.duration_seconds == pytest.approx(0.8)  # (7-3)*200ms = 800ms = 0.8s


def test_stuck_detection() -> None:
    cfg = FlightRecorderConfig(max_frames=20, stuck_detection_threshold=0.9)
    recorder = VisualFlightRecorder(config=cfg)

    # 1. Push alternating dynamic frames -> not stuck
    for i in range(12):
        recorder.push_frame(
            VisualFrame(
                frame_index=i,
                timestamp_ms=1700000000000 + i * 200,
                image_data_uri=f"data:image/png;base64,distinct_image_{i}",
            )
        )
    assert not recorder.detect_visual_stuck(min_sample_frames=10)

    # 2. Push 10 identical static frames -> declared stuck
    static_uri = "data:image/png;base64,stuck_frozen_screen"
    for i in range(12, 25):
        recorder.push_frame(
            VisualFrame(
                frame_index=i,
                timestamp_ms=1700000000000 + i * 200,
                image_data_uri=static_uri,
            )
        )
    assert recorder.detect_visual_stuck(min_sample_frames=10)


def test_slice_query_and_filtering() -> None:
    recorder = VisualFlightRecorder(FlightRecorderConfig(max_frames=10))

    recorder.push_frame(
        VisualFrame(
            frame_index=1,
            timestamp_ms=1700000000000,
            image_data_uri="data:image/png;base64,frame1",
        )
    )

    s1 = recorder.capture_failure_slice(
        trace_id="tr-1",
        session_id="sess-A",
        failure_kind="popup_overlay",
        root_cause_label="Unexpected promotional banner blocking checkout button",
    )

    s2 = recorder.capture_failure_slice(
        trace_id="tr-2",
        session_id="sess-B",
        failure_kind="captcha_slider",
        root_cause_label="Geetest slider captcha appeared requiring human intervention",
    )

    # Fetch by ID
    assert recorder.get_slice(s1.slice_id) is not None
    assert recorder.get_slice("non-existent") is None

    # Filter by session_id
    sess_a_slices = recorder.list_slices(session_id="sess-A")
    assert len(sess_a_slices) == 1
    assert sess_a_slices[0].slice_id == s1.slice_id

    # Filter by failure_kind
    captcha_slices = recorder.list_slices(failure_kind="captcha_slider")
    assert len(captcha_slices) == 1
    assert captcha_slices[0].slice_id == s2.slice_id


def test_default_recorder_singleton_and_reset() -> None:
    rec1 = get_default_visual_flight_recorder()
    rec2 = get_default_visual_flight_recorder()
    assert rec1 is rec2

    rec1.push_frame(
        VisualFrame(
            frame_index=0,
            timestamp_ms=1000,
            image_data_uri="test",
        )
    )
    assert rec1.current_buffer_size() >= 1

    rec1.reset()
    assert rec1.current_buffer_size() == 0
    assert len(rec1.list_slices()) == 0
