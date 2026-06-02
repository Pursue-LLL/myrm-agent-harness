"""Unit tests for is_within_active_hours in cron scheduler."""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.toolkits.cron.engine.helpers import is_within_active_hours
from myrm_agent_harness.toolkits.cron.types import ActiveHours


class TestIsWithinActiveHours:
    def test_none_always_true(self):
        assert is_within_active_hours(None) is True

    def test_within_normal_range(self):
        ah = ActiveHours(start="09:00", end="18:00", tz="UTC")
        noon = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
        assert is_within_active_hours(ah, now=noon) is True

    def test_outside_normal_range_before(self):
        ah = ActiveHours(start="09:00", end="18:00", tz="UTC")
        early = datetime(2026, 3, 4, 6, 0, tzinfo=UTC)
        assert is_within_active_hours(ah, now=early) is False

    def test_outside_normal_range_after(self):
        ah = ActiveHours(start="09:00", end="18:00", tz="UTC")
        late = datetime(2026, 3, 4, 20, 0, tzinfo=UTC)
        assert is_within_active_hours(ah, now=late) is False

    def test_at_start_boundary(self):
        ah = ActiveHours(start="09:00", end="18:00", tz="UTC")
        boundary = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)
        assert is_within_active_hours(ah, now=boundary) is True

    def test_at_end_boundary_excluded(self):
        ah = ActiveHours(start="09:00", end="18:00", tz="UTC")
        boundary = datetime(2026, 3, 4, 18, 0, tzinfo=UTC)
        assert is_within_active_hours(ah, now=boundary) is False

    # Cross-midnight scenarios
    def test_cross_midnight_night(self):
        ah = ActiveHours(start="22:00", end="06:00", tz="UTC")
        night = datetime(2026, 3, 4, 23, 0, tzinfo=UTC)
        assert is_within_active_hours(ah, now=night) is True

    def test_cross_midnight_early_morning(self):
        ah = ActiveHours(start="22:00", end="06:00", tz="UTC")
        morning = datetime(2026, 3, 4, 3, 0, tzinfo=UTC)
        assert is_within_active_hours(ah, now=morning) is True

    def test_cross_midnight_daytime_excluded(self):
        ah = ActiveHours(start="22:00", end="06:00", tz="UTC")
        day = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
        assert is_within_active_hours(ah, now=day) is False

    # Timezone conversion
    def test_timezone_conversion(self):
        ah = ActiveHours(start="09:00", end="18:00", tz="Asia/Shanghai")
        # 01:00 UTC = 09:00 Shanghai -> exactly at start, should be True
        utc_time = datetime(2026, 3, 4, 1, 0, tzinfo=UTC)
        assert is_within_active_hours(ah, now=utc_time) is True

    def test_timezone_conversion_outside(self):
        ah = ActiveHours(start="09:00", end="18:00", tz="Asia/Shanghai")
        # 00:00 UTC = 08:00 Shanghai -> before start, should be False
        utc_time = datetime(2026, 3, 4, 0, 0, tzinfo=UTC)
        assert is_within_active_hours(ah, now=utc_time) is False

    # Invalid inputs
    def test_invalid_time_format_returns_true(self):
        ah = ActiveHours(start="invalid", end="18:00", tz="UTC")
        assert is_within_active_hours(ah) is True

    def test_invalid_timezone_fallback(self):
        ah = ActiveHours(start="09:00", end="18:00", tz="Invalid/Zone")
        noon_utc = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
        assert is_within_active_hours(ah, now=noon_utc) is True
