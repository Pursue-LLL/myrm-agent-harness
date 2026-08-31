"""Unit tests for Event Log Integrity Gate (Item 7: SyntheticLogVerificationAndAntiSilentCorruptionGate)."""

import pytest

from myrm_agent_harness.agent.event_log.integrity_gate import (
    assert_log_integrity,
    install_log_integrity_invariants,
    verify_sequence_continuity,
    verify_session_enclosure,
)
from myrm_agent_harness.agent.event_log.types import StructuredEvent
from myrm_agent_harness.observability.invariants import (
    InvariantError,
    InvariantMode,
    InvariantSeverity,
    RuntimeInvariantRegistry,
)


def test_verify_session_enclosure_valid_and_orphan():
    """Test verification of tool events enclosed within step/turn brackets."""
    # 1. Valid enclosed flow
    valid_events = [
        {"event_type": "turn_start", "step_id": "turn_1"},
        {"event_type": "tool_start", "tool_name": "bash", "step_id": "turn_1"},
        {"event_type": "tool_end", "tool_name": "bash", "step_id": "turn_1"},
        {"event_type": "turn_end", "step_id": "turn_1"},
    ]
    assert verify_session_enclosure(valid_events) == []

    # 2. Orphan tool call outside step/turn bracket
    orphan_events = [
        {"event_type": "session_start"},
        {"event_type": "tool_start", "tool_name": "bash"},  # Orphan!
        {"event_type": "tool_end", "tool_name": "bash"},
    ]
    violations = verify_session_enclosure(orphan_events)
    assert len(violations) == 2
    assert all(v.severity == InvariantSeverity.ERROR for v in violations)
    assert any("tool_start" in v.message for v in violations)


def test_verify_sequence_continuity_monotonic_and_gaps():
    """Test detection of sequence gaps and timestamp regressions."""
    # 1. Valid sequence
    valid_seq = [
        {"seq": 0, "timestamp": 100.0, "event_type": "session_start"},
        {"seq": 1, "timestamp": 101.5, "event_type": "turn_start"},
        {"seq": 2, "timestamp": 102.0, "event_type": "turn_end"},
    ]
    assert verify_sequence_continuity(valid_seq) == []

    # 2. Sequence gap / jump
    gap_seq = [
        {"seq": 0, "timestamp": 100.0, "event_type": "session_start"},
        {"seq": 3, "timestamp": 101.0, "event_type": "turn_start"},  # Expected 1, got 3
    ]
    violations = verify_sequence_continuity(gap_seq)
    assert len(violations) == 1
    assert violations[0].severity == InvariantSeverity.ERROR
    assert "Sequence gap detected" in violations[0].message

    # 3. Timestamp regression
    regress_seq = [
        {"seq": 0, "timestamp": 105.0, "event_type": "session_start"},
        {"seq": 1, "timestamp": 90.0, "event_type": "turn_start"},  # Time travel!
    ]
    violations = verify_sequence_continuity(regress_seq)
    assert len(violations) == 1
    assert violations[0].severity == InvariantSeverity.WARN
    assert "Timestamp regression detected" in violations[0].message


def test_assert_log_integrity_strict_mode():
    """Test assert_log_integrity fail-fast behavior in strict mode."""
    corrupted_stream = [
        {"seq": 0, "timestamp": 100.0, "event_type": "session_start"},
        {"seq": 5, "timestamp": 101.0, "event_type": "tool_start"},  # Gap + Orphan
    ]

    # Non-strict mode: returns violations list
    violations = assert_log_integrity(corrupted_stream, strict=False)
    assert len(violations) >= 2

    # Strict mode: raises InvariantError immediately
    with pytest.raises(InvariantError) as exc_info:
        assert_log_integrity(corrupted_stream, strict=True)
    assert "event_log.integrity" in str(exc_info.value)


def test_install_log_integrity_invariants_integration():
    """Test registration and execution through RuntimeInvariantRegistry."""
    registry = RuntimeInvariantRegistry(mode=InvariantMode.WARN)
    install_log_integrity_invariants(registry)

    assert "event_log.integrity" in registry.registered_packages

    # Test checking package
    bad_events = [{"event_type": "tool_start", "seq": 10}]
    violations = registry.check_package("event_log.integrity", bad_events)
    assert len(violations) >= 1
