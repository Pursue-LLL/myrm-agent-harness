"""Tests for privacy_tracker — per-turn sensitivity tracking and SSE events."""

from myrm_agent_harness.agent.security.guards.privacy_tracker import (
    PrivacyTracker,
    get_pending_privacy_event,
    get_privacy_tracker,
    reset_privacy_tracker,
)
from myrm_agent_harness.agent.security.types import SensitivityLevel


class TestPrivacyTracker:
    def test_initial_state(self):
        t = PrivacyTracker()
        assert t.current_turn_level == SensitivityLevel.S1
        assert t.highest_level == SensitivityLevel.S1
        assert t.is_private is False
        assert t.turn_detections == []

    def test_record_s2(self):
        t = PrivacyTracker()
        t.record(SensitivityLevel.S2, "user_message", ["china_phone"])
        assert t.current_turn_level == SensitivityLevel.S2
        assert t.highest_level == SensitivityLevel.S2
        assert t.is_private is True
        assert len(t.turn_detections) == 1

    def test_record_s3_overrides_s2(self):
        t = PrivacyTracker()
        t.record(SensitivityLevel.S2, "user_message", ["china_phone"])
        t.record(SensitivityLevel.S3, "tool_params", ["china_id_card"])
        assert t.current_turn_level == SensitivityLevel.S3
        assert t.highest_level == SensitivityLevel.S3

    def test_s2_does_not_downgrade_from_s3(self):
        t = PrivacyTracker()
        t.record(SensitivityLevel.S3, "user_message", ["password"])
        t.record(SensitivityLevel.S2, "tool_result", ["email"])
        assert t.current_turn_level == SensitivityLevel.S3

    def test_reset_turn(self):
        t = PrivacyTracker()
        t.record(SensitivityLevel.S3, "user_message", ["password"])
        t.reset_turn()
        assert t.current_turn_level == SensitivityLevel.S1
        assert t.highest_level == SensitivityLevel.S3  # cumulative preserved
        assert t.turn_detections == []

    def test_s1_record_no_pending_event(self):
        t = PrivacyTracker()
        t.record(SensitivityLevel.S1, "user_message", [])
        assert t.drain_pending_event() is None

    def test_drain_pending_event(self):
        t = PrivacyTracker()
        t.record(SensitivityLevel.S2, "user_message", ["phone"])
        event = t.drain_pending_event()
        assert event is not None
        assert event["current_turn_level"] == "s2"
        assert event["highest_level"] == "s2"

    def test_drain_consumes_once(self):
        t = PrivacyTracker()
        t.record(SensitivityLevel.S2, "user_message", ["phone"])
        first = t.drain_pending_event()
        second = t.drain_pending_event()
        assert first is not None
        assert second is None

    def test_new_record_produces_new_event(self):
        t = PrivacyTracker()
        t.record(SensitivityLevel.S2, "user_message", ["phone"])
        t.drain_pending_event()
        t.record(SensitivityLevel.S3, "tool_params", ["password"])
        event = t.drain_pending_event()
        assert event is not None
        assert event["current_turn_level"] == "s3"


class TestContextVarAccessors:
    def test_get_privacy_tracker_lazy_init(self):
        reset_privacy_tracker()
        tracker = get_privacy_tracker()
        assert tracker is not None
        assert tracker.current_turn_level == SensitivityLevel.S1

    def test_get_same_instance(self):
        reset_privacy_tracker()
        a = get_privacy_tracker()
        b = get_privacy_tracker()
        assert a is b

    def test_reset_creates_new(self):
        reset_privacy_tracker()
        a = get_privacy_tracker()
        a.record(SensitivityLevel.S3, "test", [])
        reset_privacy_tracker()
        b = get_privacy_tracker()
        assert b.current_turn_level == SensitivityLevel.S1


class TestModuleLevelDrain:
    def test_no_tracker_returns_none(self):
        reset_privacy_tracker()
        # Fresh tracker — no events
        assert get_pending_privacy_event() is None

    def test_after_record(self):
        reset_privacy_tracker()
        tracker = get_privacy_tracker()
        tracker.record(SensitivityLevel.S2, "test", ["email"])
        event = get_pending_privacy_event()
        assert event is not None
        assert event["current_turn_level"] == "s2"
