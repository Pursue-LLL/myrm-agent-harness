"""Unit tests for SessionTaskState machine and anti-compaction Task HUD formatter.

[INPUT]
- SessionTaskState, TaskItem, format_compaction_immune_task_hud

[OUTPUT]
- Pytest test cases verifying task isolation, progress calculation, and HUD prompt injection.

[POS]
Item 31 Harness test suite. Strictly under 160 lines. Zero `Any`.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.session_task_state import (
    SessionTaskState,
    format_compaction_immune_task_hud,
)


def test_empty_session_task_state() -> None:
    """An empty task state should have 0 progress and empty HUD injection string."""
    state = SessionTaskState(session_id="session_zero")
    assert len(state.tasks) == 0
    assert state.calculate_overall_progress() == 0
    assert state.get_active_task() is None
    assert format_compaction_immune_task_hud(state) == ""


def test_add_and_update_task_lifecycle() -> None:
    """Tasks can be added, updated, and progress percent tracked accurately."""
    state = SessionTaskState(session_id="session_dev")

    # 1. Add step 1
    t1 = state.add_task(task_id="step_1", title="Initialize schema", details="Create database tables")
    assert t1.id == "step_1"
    assert t1.status == "pending"
    assert t1.progress_percent == 0

    # 2. Add step 2
    t2 = state.add_task(task_id="step_2", title="Implement REST API")
    assert t2.status == "pending"

    # Overall progress with 2 pending tasks
    assert state.calculate_overall_progress() == 0

    # 3. Transition step 1 to in_progress
    updated_t1 = state.update_task_status("step_1", status="in_progress")
    assert updated_t1 is not None
    assert updated_t1.status == "in_progress"
    assert updated_t1.progress_percent == 50
    assert state.get_active_task() == updated_t1

    # 4. Transition step 1 to completed
    completed_t1 = state.update_task_status("step_1", status="completed")
    assert completed_t1 is not None
    assert completed_t1.progress_percent == 100

    # Step 2 is now the active pending task
    assert state.get_active_task() == t2

    # Overall progress: (100 + 0) / 2 = 50%
    assert state.calculate_overall_progress() == 50


def test_custom_progress_and_remove_task() -> None:
    """Custom progress override and task removal should update overall metrics."""
    state = SessionTaskState(session_id="session_custom")

    state.add_task(task_id="t1", title="Task 1", status="in_progress", progress_percent=80)
    state.add_task(task_id="t2", title="Task 2", status="pending", progress_percent=0)

    # (80 + 0) / 2 = 40%
    assert state.calculate_overall_progress() == 40

    # Remove t2
    removed = state.remove_task("t2")
    assert removed is True
    assert len(state.tasks) == 1
    assert state.calculate_overall_progress() == 80

    # Remove non-existent task
    assert state.remove_task("t_non_existent") is False


def test_compaction_immune_hud_formatter() -> None:
    """HUD prompt injection must contain explicit anti-compaction tags and status coordinates."""
    state = SessionTaskState(session_id="chat_long_run_42")

    state.add_task(task_id="task_1", title="Run security audit", status="completed")
    state.add_task(
        task_id="task_2",
        title="Refactor frontend modal",
        status="in_progress",
        progress_percent=60,
        details="Working on React a11y dialog",
    )
    state.add_task(task_id="task_3", title="Deploy canary build", status="pending")

    hud_str = format_compaction_immune_task_hud(state)

    # Assert critical anti-compaction anchors
    assert "ANTI-COMPACTION PERSISTENT TASK HUD" in hud_str
    assert "IMMUNE TO DISTILLATION" in hud_str
    assert "chat_long_run_42" in hud_str
    assert "[x] COMPLETED" in hud_str
    assert "[-] IN PROGRESS (60%)" in hud_str
    assert "Working on React a11y dialog" in hud_str
    assert "[ ] PENDING" in hud_str
    assert "END TASK HUD" in hud_str
