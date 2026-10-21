"""Tests for failover events and notifications."""

from datetime import datetime

from myrm_agent_harness.toolkits.llms.errors import FailoverReason
from myrm_agent_harness.toolkits.llms.fallback import FailoverEvent


def test_failover_event_creation():
    """Test creating a failover event with all fields."""
    event = FailoverEvent(
        from_model="gpt-4",
        to_model="claude-3-opus",
        reason=FailoverReason.RATE_LIMIT,
        error_message="Rate limit exceeded",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        cooldown_ms=60000,
        attempt_count=3,
    )

    assert event.from_model == "gpt-4"
    assert event.to_model == "claude-3-opus"
    assert event.reason == FailoverReason.RATE_LIMIT
    assert event.error_message == "Rate limit exceeded"
    assert event.timestamp == datetime(2024, 1, 1, 12, 0, 0)
    assert event.cooldown_ms == 60000
    assert event.attempt_count == 3


def test_failover_event_default_timestamp():
    """Test that timestamp defaults to current time."""
    event = FailoverEvent(
        from_model="gpt-4",
        to_model="claude-3-opus",
        reason=FailoverReason.RATE_LIMIT,
    )

    assert event.timestamp is not None
    assert isinstance(event.timestamp, datetime)
    # Should be very recent
    assert (datetime.now() - event.timestamp).total_seconds() < 1


def test_failover_event_to_dict():
    """Test converting event to dictionary."""
    event = FailoverEvent(
        from_model="gpt-4",
        to_model="claude-3-opus",
        reason=FailoverReason.RATE_LIMIT,
        error_message="Rate limit exceeded",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        cooldown_ms=60000,
        attempt_count=3,
    )

    event_dict = event.to_dict()

    assert event_dict["from_model"] == "gpt-4"
    assert event_dict["to_model"] == "claude-3-opus"
    assert event_dict["reason"] == "rate_limit"
    assert event_dict["error_message"] == "Rate limit exceeded"
    assert event_dict["timestamp"] == "2024-01-01T12:00:00"
    assert event_dict["cooldown_ms"] == 60000
    assert event_dict["attempt_count"] == 3


def test_failover_event_minimal():
    """Test creating event with minimal required fields."""
    event = FailoverEvent(
        from_model="gpt-4",
        to_model="claude-3-opus",
        reason=FailoverReason.TIMEOUT,
    )

    assert event.from_model == "gpt-4"
    assert event.to_model == "claude-3-opus"
    assert event.reason == FailoverReason.TIMEOUT
    assert event.error_message is None
    assert event.cooldown_ms == 0
    assert event.attempt_count == 1
