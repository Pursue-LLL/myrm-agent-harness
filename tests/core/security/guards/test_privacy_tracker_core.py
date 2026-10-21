"""Tests for core.security.guards.privacy_tracker ContextVar edge cases."""

from __future__ import annotations

import contextvars

from myrm_agent_harness.core.security.guards.privacy_tracker import (
    PrivacyTracker,
    get_pending_privacy_event,
    get_pending_route_event,
    get_privacy_tracker,
)


class TestCorePrivacyContextVar:
    def test_get_privacy_tracker_lazy_init_in_empty_context(self) -> None:
        ctx = contextvars.Context()
        tracker = ctx.run(get_privacy_tracker)
        assert isinstance(tracker, PrivacyTracker)

    def test_get_pending_route_event_empty_context(self) -> None:
        ctx = contextvars.Context()
        assert ctx.run(get_pending_route_event) is None

    def test_get_pending_privacy_event_empty_context(self) -> None:
        ctx = contextvars.Context()
        assert ctx.run(get_pending_privacy_event) is None

    def test_get_pending_route_event_drains_pending(self) -> None:
        from myrm_agent_harness.core.security.guards.privacy_tracker import (
            get_privacy_tracker,
            reset_privacy_tracker,
        )

        reset_privacy_tracker()
        tracker = get_privacy_tracker()
        tracker.record_route("s2-agent")
        event = get_pending_route_event()
        assert event is not None
        assert event["route"] == "s2-agent"
        assert get_pending_route_event() is None  # consume-once
