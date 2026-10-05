"""Unit tests for Structured Task State Machine and Compaction Preservation."""

import pytest

from myrm_agent_harness.toolkits.memory.task_state import (
    CompactionStatePreservationGuard,
    StructuredTaskStateTracker,
    TaskStepStatus,
)


@pytest.fixture
def tracker() -> StructuredTaskStateTracker:
    """Fixture providing a fresh task state tracker."""
    return StructuredTaskStateTracker()


@pytest.fixture
def guard(tracker: StructuredTaskStateTracker) -> CompactionStatePreservationGuard:
    """Fixture providing a compaction preservation guard."""
    return CompactionStatePreservationGuard(tracker)


def test_task_state_initialization_and_lifecycle(tracker: StructuredTaskStateTracker) -> None:
    """Test task creation and initial state verification."""
    session_id = "sess-refactor-99"
    goal = "Refactor database connection pool and migration scripts"
    initial_todos = ["Audit current connection pool", "Migrate to asyncpg", "Write integration tests"]

    state = tracker.initialize_task(session_id, goal, initial_todos)
    assert state.session_id == session_id
    assert state.current_goal == goal
    assert state.current_phase == "planning"
    assert state.version == 1
    assert len(state.todos) == 3
    assert state.todos[0].description == "Audit current connection pool"
    assert state.todos[0].is_resolved is False

    # Retrieve state
    fetched = tracker.get_state(session_id)
    assert fetched is not None
    assert fetched.task_id == state.task_id

    # Advance phase
    tracker.advance_phase(session_id, "execution")
    assert tracker.get_state(session_id).current_phase == "execution"
    assert tracker.get_state(session_id).version == 2


def test_step_transitions(tracker: StructuredTaskStateTracker) -> None:
    """Test starting and completing individual steps."""
    session_id = "sess-steps-1"
    tracker.initialize_task(session_id, "Build authentication layer")

    # Start step 1
    tracker.start_step(session_id, "step-jwt", "Implement JWT token generation")
    state = tracker.get_state(session_id)
    assert len(state.active_steps) == 1
    assert state.active_steps[0].status == TaskStepStatus.IN_PROGRESS
    assert state.active_steps[0].started_at is not None

    # Complete step 1
    tracker.complete_step(
        session_id,
        "step-jwt",
        "Generated RSA-signed access and refresh token handlers.",
    )
    state = tracker.get_state(session_id)
    assert len(state.active_steps) == 0
    assert len(state.completed_steps) == 1
    assert state.completed_steps[0].status == TaskStepStatus.COMPLETED
    assert "RSA-signed" in (state.completed_steps[0].output_summary or "")
    assert state.completed_steps[0].completed_at is not None


def test_todo_lifecycle(tracker: StructuredTaskStateTracker) -> None:
    """Test adding, resolving, and querying checklist items."""
    session_id = "sess-todo-1"
    tracker.initialize_task(session_id, "Deploy microservice")

    todo_id = tracker.add_todo(session_id, "Configure Kubernetes ingress", priority="high")
    state = tracker.get_state(session_id)
    assert any(t.todo_id == todo_id and t.priority == "high" for t in state.todos)

    # Resolve todo
    tracker.resolve_todo(session_id, todo_id, resolution_note="Ingress YAML created and verified.")
    resolved = next(t for t in tracker.get_state(session_id).todos if t.todo_id == todo_id)
    assert resolved.is_resolved is True
    assert "YAML created" in (resolved.resolution_note or "")

    # Invalid todo ID raises KeyError
    with pytest.raises(KeyError, match="Todo 'unknown-id' not found"):
        tracker.resolve_todo(session_id, "unknown-id")


def test_blocker_management(tracker: StructuredTaskStateTracker) -> None:
    """Test blocker registration and removal."""
    session_id = "sess-blocker-1"
    tracker.initialize_task(session_id, "Run schema migration")

    tracker.add_blocker(session_id, "Waiting for DBA schema approval")
    assert "Waiting for DBA schema approval" in tracker.get_state(session_id).blockers

    # Clearing blocker
    tracker.remove_blocker(session_id, "Waiting for DBA schema approval")
    assert "Waiting for DBA schema approval" not in tracker.get_state(session_id).blockers


def test_compaction_anchor_rendering(tracker: StructuredTaskStateTracker) -> None:
    """Test rendering deterministic Markdown task state anchor block."""
    session_id = "sess-render-1"
    tracker.initialize_task(
        session_id,
        "Upgrade Python packages to latest versions",
        ["Update pyproject.toml", "Run lockfile update"],
    )
    tracker.start_step(session_id, "s1", "Check breaking changes in pydantic v2")
    tracker.complete_step(session_id, "s1", "Identified 4 validator changes needed")
    tracker.add_blocker(session_id, "Pending CI server maintenance")

    anchor = tracker.render_compaction_anchor(session_id)
    assert "### [ACTIVE TASK STATE ANCHOR - PRESERVED & DO NOT COMPACT]" in anchor
    assert "Upgrade Python packages to latest versions" in anchor
    assert "Identified 4 validator changes needed" in anchor
    assert "[ ] [NORMAL] Update pyproject.toml" in anchor
    assert "Pending CI server maintenance" in anchor


def test_compaction_preservation_guard(
    tracker: StructuredTaskStateTracker,
    guard: CompactionStatePreservationGuard,
) -> None:
    """Test guard preserves structured state and formats compound context across compaction."""
    session_id = "sess-compact-1"
    tracker.initialize_task(session_id, "Refactor frontend auth route")
    tracker.start_step(session_id, "step-auth", "Inspect login page")
    tracker.complete_step(session_id, "step-auth", "Identified memory leak in useEffect")

    v_before = tracker.get_state(session_id).version
    raw_summary = "User asked about auth route. Agent inspected login page and found a memory leak."

    # Apply compaction
    payload = guard.apply_compaction_anchor(session_id, raw_summary)
    assert payload.session_id == session_id
    assert payload.raw_summary == raw_summary
    assert payload.structured_state.version > v_before
    assert len(payload.structured_state.completed_steps) == 1

    # Format composite context
    composite = guard.assemble_compacted_context(session_id, raw_summary)
    assert "### [ACTIVE TASK STATE ANCHOR - PRESERVED & DO NOT COMPACT]" in composite
    assert "### [DIALOGUE ROLLING SUMMARY]" in composite
    assert "User asked about auth route" in composite


def test_compaction_guard_untracked_session_raises(
    guard: CompactionStatePreservationGuard,
) -> None:
    """Compacting an untracked session must raise KeyError."""
    with pytest.raises(KeyError, match="no structured task state tracked"):
        guard.apply_compaction_anchor("non-existent-session", "Some summary")
