"""Unit tests for Runtime Invariant Registry Pack (RuntimeInvariantRegistryPack)."""

import pytest

from myrm_agent_harness.observability.invariants import (
    InvariantError,
    InvariantMode,
    InvariantSeverity,
    InvariantViolation,
    RuntimeInvariantRegistry,
    check_agent_state_transition,
    check_sequence_continuity,
    check_session_event_pairing,
    check_step_enclosure,
    check_todo_structure_integrity,
    install_core_invariants,
)


def test_invariant_registry_registration_and_modes():
    """Test invariant registration, mode switching, and allowlist/blocklist filtering."""
    registry = RuntimeInvariantRegistry(mode=InvariantMode.WARN)

    def dummy_checker(ctx: object) -> list[InvariantViolation]:
        if ctx == "fail":
            return [
                InvariantViolation(
                    package_name="test.pkg",
                    invariant_name="dummy_rule",
                    message="Dummy test failure",
                    severity=InvariantSeverity.ERROR,
                )
            ]
        return []

    registry.register("test.pkg", "dummy_rule", dummy_checker)
    assert "test.pkg" in registry.registered_packages
    assert registry.total_checkers_count == 1

    # 1. WARN mode: violations are returned, not raised
    violations = registry.check_package("test.pkg", "fail")
    assert len(violations) == 1
    assert violations[0].invariant_name == "dummy_rule"

    # 2. STRICT mode: raises InvariantError
    registry.set_mode(InvariantMode.STRICT)
    with pytest.raises(InvariantError) as exc_info:
        registry.check_package("test.pkg", "fail")
    assert "[INVARIANT:test.pkg:dummy_rule]" in str(exc_info.value)

    # 3. DISABLED mode: returns empty list immediately
    registry.set_mode(InvariantMode.DISABLED)
    assert registry.check_package("test.pkg", "fail") == []


def test_session_event_pairing_invariant():
    """Test tool_start and tool_end pairing verification."""
    # Valid paired stream
    valid_events = [
        {"event_type": "tool_start", "tool_call_id": "call_1", "tool_name": "bash"},
        {"event_type": "tool_end", "tool_call_id": "call_1", "tool_name": "bash"},
    ]
    assert check_session_event_pairing(valid_events) == []

    # Unclosed tool call
    unclosed_events = [
        {"event_type": "tool_start", "tool_call_id": "call_2", "tool_name": "browser"},
    ]
    violations = check_session_event_pairing(unclosed_events)
    assert len(violations) == 1
    assert violations[0].severity == InvariantSeverity.ERROR
    assert "Unclosed tool call 'browser'" in violations[0].message

    # Orphan terminal event
    orphan_events = [
        {"event_type": "tool_end", "tool_call_id": "call_orphan", "tool_name": "search"},
    ]
    violations = check_session_event_pairing(orphan_events)
    assert len(violations) == 1
    assert violations[0].severity == InvariantSeverity.WARN
    assert "Orphan terminal event" in violations[0].message


def test_agent_state_transition_invariant():
    """Test state machine valid transitions and illegal reverse jumps."""
    # Valid transitions
    assert check_agent_state_transition({"from_state": "CREATED", "to_state": "RUNNING"}) == []
    assert check_agent_state_transition({"from_state": "RUNNING", "to_state": "COMPLETED"}) == []
    assert check_agent_state_transition(("IDLE", "RUNNING")) == []

    # Illegal transition: COMPLETED -> RUNNING directly
    violations = check_agent_state_transition({"from_state": "COMPLETED", "to_state": "RUNNING"})
    assert len(violations) == 1
    assert violations[0].severity == InvariantSeverity.ERROR
    assert "Illegal state transition" in violations[0].message

    # Unknown origin state
    violations = check_agent_state_transition({"from_state": "GHOST_STATE", "to_state": "RUNNING"})
    assert len(violations) == 1
    assert "Unknown origin state" in violations[0].message


def test_todo_structure_integrity_invariant():
    """Test Todo list ID uniqueness, content, and status validity."""
    # Valid Todo list
    valid_todos = [
        {"id": "todo_1", "content": "Step 1", "status": "in_progress"},
        {"id": "todo_2", "content": "Step 2", "status": "pending"},
    ]
    assert check_todo_structure_integrity(valid_todos) == []

    # Duplicate IDs and invalid status
    bad_todos = [
        {"id": "todo_dup", "content": "First", "status": "pending"},
        {"id": "todo_dup", "content": "Duplicate", "status": "INVALID_STATUS"},
        {"id": "", "content": "Missing ID", "status": "pending"},
    ]
    violations = check_todo_structure_integrity(bad_todos)
    assert len(violations) >= 3
    messages = [v.message for v in violations]
    assert any("Duplicate Todo ID 'todo_dup'" in msg for msg in messages)
    assert any("invalid status 'INVALID_STATUS'" in msg for msg in messages)
    assert any("missing or empty id" in msg for msg in messages)


def test_step_enclosure_invariant():
    """Test step/turn bracket enclosure verification."""
    # Valid enclosed sequence
    valid_events = [
        {"event_type": "task_step_start", "step_id": "s1"},
        {"event_type": "tool_start", "tool_call_id": "c1"},
        {"event_type": "tool_end", "tool_call_id": "c1"},
        {"event_type": "assistant_message", "content": "Done"},
        {"event_type": "task_step_end", "step_id": "s1"},
    ]
    assert check_step_enclosure(valid_events) == []

    # Orphan payload outside step bracket
    orphan_payload = [
        {"event_type": "user_message", "content": "Hello outside"},
    ]
    violations = check_step_enclosure(orphan_payload)
    assert len(violations) == 1
    assert "outside an active step/turn enclosure" in violations[0].message

    # Orphan closing bracket
    orphan_close = [
        {"event_type": "task_step_end", "step_id": "s_ghost"},
    ]
    violations = check_step_enclosure(orphan_close)
    assert len(violations) == 1
    assert "without matching start step/turn bracket" in violations[0].message

    # Unclosed step bracket
    unclosed_step = [
        {"event_type": "step_start", "step_id": "s_open"},
        {"event_type": "thought", "content": "Thinking..."},
    ]
    violations = check_step_enclosure(unclosed_step)
    assert len(violations) == 1
    assert "never received closing bracket" in violations[0].message


def test_sequence_continuity_invariant():
    """Test monotonic sequence numbers and gap-free detection."""
    # Valid consecutive sequence
    valid_seq = [
        {"seq": 1, "event_type": "step_start"},
        {"seq": 2, "event_type": "thought"},
        {"seq": 3, "event_type": "step_end"},
    ]
    assert check_sequence_continuity(valid_seq) == []

    # Sequence gap detected (1 -> 3, missing 2)
    gap_seq = [
        {"seq": 1, "event_type": "step_start"},
        {"seq": 3, "event_type": "step_end"},
    ]
    violations = check_sequence_continuity(gap_seq)
    assert len(violations) == 1
    assert "Sequence gap detected" in violations[0].message
    assert violations[0].details["gap_size"] == 1

    # Non-monotonic sequence (2 -> 1)
    non_mono_seq = [
        {"seq": 2, "event_type": "step_start"},
        {"seq": 1, "event_type": "thought"},
    ]
    violations = check_sequence_continuity(non_mono_seq)
    assert len(violations) == 1
    assert "Non-monotonic sequence number" in violations[0].message

    # Non-integer sequence
    bad_type_seq = [
        {"seq": "invalid_number", "event_type": "step_start"},
    ]
    violations = check_sequence_continuity(bad_type_seq)
    assert len(violations) == 1
    assert "Non-integer sequence number" in violations[0].message


def test_install_core_invariants_and_check_all():
    """Test full integration with install_core_invariants and check_all."""
    registry = RuntimeInvariantRegistry(mode=InvariantMode.WARN)
    install_core_invariants(registry)

    assert "session.events" in registry.registered_packages
    assert "agent.lifecycle" in registry.registered_packages
    assert "toolkits.todo" in registry.registered_packages
    assert registry.total_checkers_count == 5
