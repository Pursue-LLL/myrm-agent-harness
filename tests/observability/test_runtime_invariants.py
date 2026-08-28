"""Unit tests for Runtime Invariant Registry Pack (RuntimeInvariantRegistryPack)."""

import pytest

from myrm_agent_harness.observability.invariants import (
    InvariantError,
    InvariantMode,
    InvariantSeverity,
    InvariantViolation,
    RuntimeInvariantRegistry,
    check_agent_state_transition,
    check_session_event_pairing,
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


def test_install_core_invariants_and_check_all():
    """Test full integration with install_core_invariants and check_all."""
    registry = RuntimeInvariantRegistry(mode=InvariantMode.WARN)
    install_core_invariants(registry)

    assert "session.events" in registry.registered_packages
    assert "agent.lifecycle" in registry.registered_packages
    assert "toolkits.todo" in registry.registered_packages
    assert registry.total_checkers_count == 3
