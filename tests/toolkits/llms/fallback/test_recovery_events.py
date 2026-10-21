"""Unit tests for RecoveryEvent."""

from __future__ import annotations

from datetime import datetime

from myrm_agent_harness.toolkits.llms.fallback.events import RecoveryEvent


def test_recovery_event_creation() -> None:
    """Test basic recovery event creation."""
    event = RecoveryEvent(
        model="gpt-4",
        downtime_ms=5000,
        probe_count=3,
    )

    assert event.model == "gpt-4"
    assert event.downtime_ms == 5000
    assert event.probe_count == 3
    assert event.was_in_cooldown is True
    assert isinstance(event.timestamp, datetime)


def test_recovery_event_with_timestamp() -> None:
    """Test recovery event with explicit timestamp."""
    now = datetime.now()
    event = RecoveryEvent(
        model="claude-3-opus-20240229",
        downtime_ms=3000,
        probe_count=2,
        timestamp=now,
        was_in_cooldown=False,
    )

    assert event.timestamp == now
    assert event.was_in_cooldown is False


def test_recovery_event_to_dict() -> None:
    """Test recovery event serialization."""
    now = datetime.now()
    event = RecoveryEvent(
        model="gpt-4",
        downtime_ms=5000,
        probe_count=3,
        timestamp=now,
        was_in_cooldown=True,
    )

    result = event.to_dict()

    assert result["model"] == "gpt-4"
    assert result["downtime_ms"] == 5000
    assert result["probe_count"] == 3
    assert result["timestamp"] == now.isoformat()
    assert result["was_in_cooldown"] is True


def test_recovery_event_default_timestamp() -> None:
    """Test that default timestamp is set correctly."""
    event = RecoveryEvent(
        model="gpt-4",
        downtime_ms=5000,
        probe_count=3,
    )

    assert event.timestamp is not None
    assert isinstance(event.timestamp, datetime)
    assert (datetime.now() - event.timestamp).total_seconds() < 1.0
