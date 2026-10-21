"""Unit tests for Coding Agent Wave Preset Pipeline (Item 45).

[INPUT]
- CodingAgentWaveEngine, WavePresetConfig, WaveStageEnum, WaveTaskStatusEnum.

[OUTPUT]
- Pytest cases verifying wave initialization, multi-model role routing,
  strict stage gate validation, full lifecycle advancement, and JSON export.

[POS]
- myrm-agent-harness/tests/agent/coordination/test_coding_wave_orchestrator.py
"""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.agent.coordination.wave_orchestrator import (
    CodingAgentWaveEngine,
    CodingWaveError,
    CodingWaveGateError,
    WaveStageEnum,
    WaveTaskStatusEnum,
)


def test_create_wave_session_and_default_topology() -> None:
    engine = CodingAgentWaveEngine()
    progress = engine.create_wave_session("session_wave_101")

    assert progress.session_id == "session_wave_101"
    assert progress.current_stage == WaveStageEnum.PLANNING
    assert progress.is_completed is False
    assert len(progress.tasks) == 7

    # Verify initial task states
    plan_task = progress.tasks[0]
    assert plan_task.task_id == "task_plan_architecture"
    assert plan_task.role == "tech-lead"
    assert plan_task.model_override == "kimi-k3"
    assert plan_task.status == WaveTaskStatusEnum.IN_PROGRESS

    # Other wave tasks are pending initially
    backend_task = next(t for t in progress.tasks if t.task_id == "task_wave1_backend")
    assert backend_task.role == "backend-dev"
    assert backend_task.model_override == "ornith-1.5"
    assert backend_task.status == WaveTaskStatusEnum.PENDING


def test_task_status_updates() -> None:
    engine = CodingAgentWaveEngine()
    engine.create_wave_session("session_wave_102")

    updated = engine.update_task_status(
        session_id="session_wave_102",
        task_id="task_plan_architecture",
        status=WaveTaskStatusEnum.COMPLETED,
        output_summary="Detailed architectural blueprint completed with 3-tier boundary.",
    )
    assert updated.status == WaveTaskStatusEnum.COMPLETED
    assert "Detailed architectural blueprint" in str(updated.output_summary)

    # Missing session raises CodingWaveError
    with pytest.raises(CodingWaveError, match="not found"):
        engine.update_task_status("missing_session", "task_plan_architecture", WaveTaskStatusEnum.COMPLETED)

    # Missing task raises CodingWaveError
    with pytest.raises(CodingWaveError, match="Task 'non_existent' not found"):
        engine.update_task_status("session_wave_102", "non_existent", WaveTaskStatusEnum.COMPLETED)


def test_strict_stage_gate_advancement() -> None:
    engine = CodingAgentWaveEngine()
    engine.create_wave_session("session_wave_103")

    # 1. Attempt advancement while planning task is still IN_PROGRESS -> blocked by stage gate
    with pytest.raises(CodingWaveGateError, match="Stage gate blocked"):
        engine.advance_stage("session_wave_103")

    # 2. Complete planning task
    engine.update_task_status(
        "session_wave_103",
        "task_plan_architecture",
        WaveTaskStatusEnum.COMPLETED,
    )

    # 3. Advancement succeeds, moving from PLANNING to WAVE1_DEV
    progress = engine.advance_stage("session_wave_103")
    assert progress.current_stage == WaveStageEnum.WAVE1_DEV

    # WAVE1_DEV tasks are now automatically activated to IN_PROGRESS
    backend_task = next(t for t in progress.tasks if t.task_id == "task_wave1_backend")
    frontend_task = next(t for t in progress.tasks if t.task_id == "task_wave1_frontend")
    assert backend_task.status == WaveTaskStatusEnum.IN_PROGRESS
    assert frontend_task.status == WaveTaskStatusEnum.IN_PROGRESS


def test_full_pipeline_progression_to_completion() -> None:
    engine = CodingAgentWaveEngine()
    engine.create_wave_session("session_wave_104")

    # Complete PLANNING
    engine.update_task_status("session_wave_104", "task_plan_architecture", WaveTaskStatusEnum.COMPLETED)
    engine.advance_stage("session_wave_104")

    # Complete WAVE1_DEV
    engine.update_task_status("session_wave_104", "task_wave1_backend", WaveTaskStatusEnum.COMPLETED)
    engine.update_task_status("session_wave_104", "task_wave1_frontend", WaveTaskStatusEnum.COMPLETED)
    engine.advance_stage("session_wave_104")

    # Complete WAVE2_REVIEW
    engine.update_task_status("session_wave_104", "task_wave2_review", WaveTaskStatusEnum.COMPLETED)
    engine.advance_stage("session_wave_104")

    # Complete WAVE3_TEST
    engine.update_task_status("session_wave_104", "task_wave3_test", WaveTaskStatusEnum.COMPLETED)
    engine.advance_stage("session_wave_104")

    # Complete WAVE4_VISUAL
    engine.update_task_status("session_wave_104", "task_wave4_visual", WaveTaskStatusEnum.COMPLETED)
    engine.advance_stage("session_wave_104")

    # Complete WAVE5_EVAL
    engine.update_task_status("session_wave_104", "task_wave5_eval", WaveTaskStatusEnum.COMPLETED)
    final_progress = engine.advance_stage("session_wave_104")

    assert final_progress.is_completed is True

    # Advancing an already completed session throws gate error
    with pytest.raises(CodingWaveGateError, match="already fully completed"):
        engine.advance_stage("session_wave_104")


def test_export_progress_json() -> None:
    engine = CodingAgentWaveEngine()
    engine.create_wave_session("session_wave_105")

    raw_json = engine.export_progress_json("session_wave_105")
    parsed = json.loads(raw_json)

    assert parsed["session_id"] == "session_wave_105"
    assert parsed["current_stage"] == "planning"
    assert parsed["is_completed"] is False
    assert len(parsed["tasks"]) == 7
    assert parsed["tasks"][0]["task_id"] == "task_plan_architecture"
