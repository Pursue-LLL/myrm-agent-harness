"""Unit tests for extended event information (session_id, request_id, etc.)."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.errors import FailoverReason
from myrm_agent_harness.toolkits.llms.fallback.events import FailoverEvent


def test_failover_event_with_session_context() -> None:
    """Test failover event with session_id and request_id."""
    event = FailoverEvent(
        from_model="gpt-4",
        to_model="claude-3-opus-20240229",
        reason=FailoverReason.RATE_LIMIT,
        session_id="session-123",
        request_id="req-456",
        available_candidates=["gpt-4", "claude-3-opus-20240229", "gpt-3.5-turbo"],
        scenario="REALTIME",
    )

    assert event.session_id == "session-123"
    assert event.request_id == "req-456"
    assert event.available_candidates == [
        "gpt-4",
        "claude-3-opus-20240229",
        "gpt-3.5-turbo",
    ]
    assert event.scenario == "REALTIME"


def test_failover_event_extended_to_dict() -> None:
    """Test that extended fields are serialized correctly."""
    event = FailoverEvent(
        from_model="gpt-4",
        to_model="claude-3-opus-20240229",
        reason=FailoverReason.RATE_LIMIT,
        session_id="session-123",
        request_id="req-456",
        available_candidates=["gpt-4", "claude-3-opus-20240229"],
        scenario="REALTIME",
    )

    result = event.to_dict()

    assert result["session_id"] == "session-123"
    assert result["request_id"] == "req-456"
    assert result["available_candidates"] == ["gpt-4", "claude-3-opus-20240229"]
    assert result["scenario"] == "REALTIME"


def test_failover_event_without_optional_context() -> None:
    """Test that optional context fields don't appear when not set."""
    event = FailoverEvent(
        from_model="gpt-4",
        to_model="claude-3-opus-20240229",
        reason=FailoverReason.RATE_LIMIT,
    )

    result = event.to_dict()

    assert "session_id" not in result
    assert "request_id" not in result
    # Empty list should not be in the dict
    assert "available_candidates" not in result
    assert "scenario" not in result


def test_failover_event_partial_context() -> None:
    """Test event with some optional fields set."""
    event = FailoverEvent(
        from_model="gpt-4",
        to_model="claude-3-opus-20240229",
        reason=FailoverReason.RATE_LIMIT,
        session_id="session-123",
        scenario="BATCH",
    )

    result = event.to_dict()

    assert result["session_id"] == "session-123"
    assert result["scenario"] == "BATCH"
    assert "request_id" not in result
    assert "available_candidates" not in result
