"""Tests for privacy_tracker — per-turn sensitivity tracking and SSE events."""

import contextvars

from myrm_agent_harness.agent.security.guards.privacy_tracker import (
    PrivacyTracker,
    get_pending_privacy_event,
    get_pending_route_event,
    get_privacy_policy,
    get_privacy_tracker,
    reset_privacy_tracker,
    set_privacy_policy,
)
from myrm_agent_harness.agent.security.types import PrivacyPolicy, SensitivityLevel


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


class TestPrivacyPolicyContext:
    def test_set_and_get_policy(self):
        policy = PrivacyPolicy()
        set_privacy_policy(policy)
        assert get_privacy_policy() is policy

    def test_default_policy_when_unset(self):
        set_privacy_policy(None)
        policy = get_privacy_policy()
        assert policy is not None
        assert isinstance(policy, PrivacyPolicy)


class TestRouteEvents:
    def test_route_event_flow(self):
        t = PrivacyTracker()
        t.record_route("s3-agent")
        assert t.route_label == "s3-agent"
        event = t.drain_pending_route_event()
        assert event == {"route": "s3-agent", "level": "s1"}
        assert t.drain_pending_route_event() is None  # consume-once

    def test_route_event_unknown_when_no_label(self):
        t = PrivacyTracker()
        # _pending_route_event forced true only via record_route; drain twice path
        assert t.drain_pending_route_event() is None

    def test_reset_turn_clears_route(self):
        t = PrivacyTracker()
        t.record_route("s2-agent")
        t.reset_turn()
        assert t.route_label is None
        assert t.drain_pending_route_event() is None


class TestFreshContextLookupError:
    def test_pending_event_survives_empty_context(self):
        ctx = contextvars.Context()
        assert ctx.run(get_pending_privacy_event) is None

    def test_pending_route_event_survives_empty_context(self):
        ctx = contextvars.Context()
        assert ctx.run(get_pending_route_event) is None

    def test_s3_event_includes_policy_action(self):
        reset_privacy_tracker()
        tracker = get_privacy_tracker()
        tracker.record(SensitivityLevel.S3, "tool_params", ["password"])
        event = tracker.drain_pending_event()
        assert event is not None
        assert event["current_turn_level"] == "s3"
        assert "action" in event
