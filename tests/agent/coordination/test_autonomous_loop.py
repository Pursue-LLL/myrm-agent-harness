"""Unit tests for Goal-Driven Autonomous Orchestration Loop (Item 38).

[INPUT]
- myrm_agent_harness.agent.coordination.autonomous_loop::{
    AutonomousLoopConfig,
    AutonomousLoopController,
    AutonomousLoopState,
    AutonomousLoopStep,
    OrchestrationMode,
    StepStatus,
  }

[OUTPUT]
- Pytest cases verifying autonomous pacing, watchdog step limits, human approval
  pauses, error handling, mode toggles, and loop completion.

[POS]
- myrm-agent-harness/tests/agent/coordination/test_autonomous_loop.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.coordination.autonomous_loop import (
    AutonomousLoopConfig,
    AutonomousLoopController,
    OrchestrationMode,
    StepStatus,
)


@pytest.fixture
def controller() -> AutonomousLoopController:
    return AutonomousLoopController()


def test_start_loop_validations(controller: AutonomousLoopController) -> None:
    with pytest.raises(ValueError, match="session_id cannot be blank"):
        controller.start_loop(session_id="  ", goal_id="goal-1")

    with pytest.raises(ValueError, match="goal_id cannot be blank"):
        controller.start_loop(session_id="session-1", goal_id="  ")


def test_start_loop_modes(controller: AutonomousLoopController) -> None:
    state_auto = controller.start_loop(
        session_id="sess-auto",
        goal_id="goal-auto",
        mode=OrchestrationMode.AUTONOMOUS,
        config=AutonomousLoopConfig(max_autonomous_steps=5),
    )
    assert state_auto.session_id == "sess-auto"
    assert state_auto.goal_id == "goal-auto"
    assert state_auto.mode == OrchestrationMode.AUTONOMOUS
    assert state_auto.is_active is True
    assert state_auto.max_steps == 5
    assert state_auto.current_step == 0
    assert len(state_auto.history) == 0

    state_sup = controller.start_loop(
        session_id="sess-sup",
        goal_id="goal-sup",
        mode=OrchestrationMode.SUPERVISED,
    )
    assert state_sup.mode == OrchestrationMode.SUPERVISED
    assert state_sup.is_active is False
    assert "Supervised mode" in state_sup.pause_reason


def test_advance_step_normal_progression(controller: AutonomousLoopController) -> None:
    controller.start_loop(
        session_id="sess-advance",
        goal_id="goal-advance",
        config=AutonomousLoopConfig(max_autonomous_steps=10),
    )

    state = controller.advance_step(
        session_id="sess-advance",
        action_type="subagent_task",
        description="Dispatch research task to Researcher",
        metadata={"subagent": "researcher_1"},
    )

    assert state.current_step == 1
    assert state.is_active is True
    assert state.mode == OrchestrationMode.AUTONOMOUS
    assert len(state.history) == 1
    assert state.history[0].step_index == 1
    assert state.history[0].action_type == "subagent_task"
    assert state.history[0].status == StepStatus.SUCCESS
    assert state.history[0].metadata["subagent"] == "researcher_1"


def test_advance_step_max_steps_watchdog(controller: AutonomousLoopController) -> None:
    controller.start_loop(
        session_id="sess-watchdog",
        goal_id="goal-watchdog",
        config=AutonomousLoopConfig(max_autonomous_steps=2),
    )

    state_1 = controller.advance_step(
        session_id="sess-watchdog",
        action_type="tool_execution",
        description="Run linter",
    )
    assert state_1.current_step == 1
    assert state_1.mode == OrchestrationMode.AUTONOMOUS

    # Step 2: reaches max_steps=2
    state_2 = controller.advance_step(
        session_id="sess-watchdog",
        action_type="tool_execution",
        description="Run unit tests",
    )
    assert state_2.current_step == 2
    assert state_2.mode == OrchestrationMode.PAUSED
    assert state_2.is_active is False
    assert "Max autonomous steps limit reached" in state_2.pause_reason

    # Step 3: attempting to advance while already at ceiling
    state_3 = controller.advance_step(
        session_id="sess-watchdog",
        action_type="tool_execution",
        description="Exceeding limit",
    )
    assert state_3.current_step == 2
    assert state_3.mode == OrchestrationMode.PAUSED


def test_advance_step_human_approval_pause(controller: AutonomousLoopController) -> None:
    controller.start_loop(
        session_id="sess-approval",
        goal_id="goal-approval",
        config=AutonomousLoopConfig(max_autonomous_steps=10, pause_on_approval=True),
    )

    state = controller.advance_step(
        session_id="sess-approval",
        action_type="deploy_prod",
        description="Deploy artifacts to production cloud",
        requires_approval=True,
    )

    assert state.current_step == 1
    assert state.mode == OrchestrationMode.PAUSED
    assert state.is_active is False
    assert "requires human approval" in state.pause_reason
    assert state.history[0].status == StepStatus.PAUSED


def test_advance_step_error_pause(controller: AutonomousLoopController) -> None:
    controller.start_loop(
        session_id="sess-err",
        goal_id="goal-err",
        config=AutonomousLoopConfig(pause_on_error=True),
    )

    state = controller.advance_step(
        session_id="sess-err",
        action_type="run_migration",
        description="Database schema migration",
        is_error=True,
    )

    assert state.current_step == 1
    assert state.mode == OrchestrationMode.PAUSED
    assert state.is_active is False
    assert "Step encountered execution error" in state.pause_reason
    assert state.history[0].status == StepStatus.FAILED


def test_lifecycle_and_mode_switching(controller: AutonomousLoopController) -> None:
    controller.start_loop(session_id="sess-life", goal_id="goal-life")

    # Switch to SUPERVISED
    state_sup = controller.set_mode(
        session_id="sess-life",
        mode=OrchestrationMode.SUPERVISED,
    )
    assert state_sup.mode == OrchestrationMode.SUPERVISED
    assert state_sup.is_active is False

    # Resume to AUTONOMOUS
    state_auto = controller.set_mode(
        session_id="sess-life",
        mode=OrchestrationMode.AUTONOMOUS,
    )
    assert state_auto.mode == OrchestrationMode.AUTONOMOUS
    assert state_auto.is_active is True

    # Complete loop
    state_done = controller.complete_loop(session_id="sess-life", summary="All objectives met")
    assert state_done.mode == OrchestrationMode.COMPLETED
    assert state_done.is_active is False
    assert state_done.pause_reason == "All objectives met"

    # List & get & reset
    assert len(controller.list_active_loops()) == 1
    assert controller.get_state("sess-life") is not None
    assert controller.reset_loop("sess-life") is True
    assert controller.get_state("sess-life") is None
