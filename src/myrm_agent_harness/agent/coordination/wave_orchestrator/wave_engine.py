"""Coding Agent Wave Preset Pipeline Engine (Item 45).

[INPUT]
- Session ID, WavePresetConfig, task status updates, and stage advancement signals.

[OUTPUT]
- CodingAgentWaveEngine governing wave progression, strict stage gate validation,
  and orchestration_progress.json generation.

[POS]
- Harness coordination layer engine for optional coding profile multi-model wave execution.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import UTC, datetime

from .types import (
    WaveExecutionProgress,
    WavePresetConfig,
    WaveStageEnum,
    WaveTaskNode,
    WaveTaskStatusEnum,
)

logger = logging.getLogger(__name__)

STAGE_ORDER: tuple[WaveStageEnum, ...] = (
    WaveStageEnum.PLANNING,
    WaveStageEnum.WAVE1_DEV,
    WaveStageEnum.WAVE2_REVIEW,
    WaveStageEnum.WAVE3_TEST,
    WaveStageEnum.WAVE4_VISUAL,
    WaveStageEnum.WAVE5_EVAL,
)


class CodingWaveError(ValueError):
    """Base exception for wave pipeline operations."""


class CodingWaveGateError(CodingWaveError):
    """Raised when stage advancement is blocked by unfinished or failed wave tasks."""


def _build_default_wave_tasks(preset: WavePresetConfig) -> list[WaveTaskNode]:
    routing = preset.role_model_routing
    return [
        WaveTaskNode(
            task_id="task_plan_architecture",
            stage=WaveStageEnum.PLANNING,
            title="System Architecture & Specification Blueprint",
            role="tech-lead",
            model_override=routing.get("tech-lead", "kimi-k3"),
            status=WaveTaskStatusEnum.IN_PROGRESS,
        ),
        WaveTaskNode(
            task_id="task_wave1_backend",
            stage=WaveStageEnum.WAVE1_DEV,
            title="Backend Core Services & API Implementation",
            role="backend-dev",
            model_override=routing.get("backend-dev", "ornith-1.5"),
            status=WaveTaskStatusEnum.PENDING,
        ),
        WaveTaskNode(
            task_id="task_wave1_frontend",
            stage=WaveStageEnum.WAVE1_DEV,
            title="Frontend UI Components & State Binding",
            role="frontend-dev",
            model_override=routing.get("frontend-dev", "kimi-k3"),
            status=WaveTaskStatusEnum.PENDING,
        ),
        WaveTaskNode(
            task_id="task_wave2_review",
            stage=WaveStageEnum.WAVE2_REVIEW,
            title="Adversarial Code & Security Review",
            role="code-reviewer",
            model_override=routing.get("code-reviewer", "glm-5.3"),
            status=WaveTaskStatusEnum.PENDING,
        ),
        WaveTaskNode(
            task_id="task_wave3_test",
            stage=WaveStageEnum.WAVE3_TEST,
            title="Automated Unit & Integration Test Suite",
            role="qa-tester",
            model_override=routing.get("qa-tester", "ornith-1.5"),
            status=WaveTaskStatusEnum.PENDING,
        ),
        WaveTaskNode(
            task_id="task_wave4_visual",
            stage=WaveStageEnum.WAVE4_VISUAL,
            title="Visual Regression & Accessibility Check",
            role="frontend-dev",
            model_override=routing.get("frontend-dev", "kimi-k3"),
            status=WaveTaskStatusEnum.PENDING,
        ),
        WaveTaskNode(
            task_id="task_wave5_eval",
            stage=WaveStageEnum.WAVE5_EVAL,
            title="End-to-End Delivery & Acceptance Verification",
            role="acceptance-eval",
            model_override=routing.get("acceptance-eval", "kimi-k3"),
            status=WaveTaskStatusEnum.PENDING,
        ),
    ]


class CodingAgentWaveEngine:
    """Manages wave-based software engineering pipelines with strict stage gates."""

    def __init__(self, default_preset: WavePresetConfig | None = None) -> None:
        self._preset = default_preset or WavePresetConfig()
        self._sessions: dict[str, WaveExecutionProgress] = {}

    def create_wave_session(
        self,
        session_id: str,
        preset: WavePresetConfig | None = None,
        custom_tasks: list[WaveTaskNode] | None = None,
    ) -> WaveExecutionProgress:
        """Initialize a new multi-wave development session with preconfigured tasks."""
        if not session_id.strip():
            msg = "Session ID cannot be empty."
            raise CodingWaveError(msg)

        active_preset = preset or self._preset
        initial_tasks = custom_tasks if custom_tasks is not None else _build_default_wave_tasks(active_preset)

        progress = WaveExecutionProgress(
            session_id=session_id,
            current_stage=WaveStageEnum.PLANNING,
            tasks=tuple(initial_tasks),
            is_completed=False,
            updated_at=datetime.now(tz=UTC),
        )
        self._sessions[session_id] = progress
        logger.info("Initialized coding wave session '%s' with %d tasks", session_id, len(initial_tasks))
        return progress

    def get_progress(self, session_id: str) -> WaveExecutionProgress | None:
        """Retrieve the wave execution progress for the given session ID."""
        return self._sessions.get(session_id)

    def update_task_status(
        self,
        session_id: str,
        task_id: str,
        status: WaveTaskStatusEnum,
        output_summary: str | None = None,
    ) -> WaveTaskNode:
        """Update the status and optional summary for a specific task node in session."""
        progress = self._sessions.get(session_id)
        if progress is None:
            msg = f"Wave session '{session_id}' not found."
            raise CodingWaveError(msg)

        updated_tasks: list[WaveTaskNode] = []
        found_node: WaveTaskNode | None = None

        for task in progress.tasks:
            if task.task_id == task_id:
                new_summary = output_summary if output_summary is not None else task.output_summary
                found_node = dataclasses.replace(task, status=status, output_summary=new_summary)
                updated_tasks.append(found_node)
            else:
                updated_tasks.append(task)

        if found_node is None:
            msg = f"Task '{task_id}' not found in wave session '{session_id}'."
            raise CodingWaveError(msg)

        self._sessions[session_id] = dataclasses.replace(
            progress,
            tasks=tuple(updated_tasks),
            updated_at=datetime.now(tz=UTC),
        )
        logger.info("Task '%s' in session '%s' transitioned to %s", task_id, session_id, status)
        return found_node

    def advance_stage(self, session_id: str) -> WaveExecutionProgress:
        """Advance the wave session to the subsequent stage if all current tasks passed."""
        progress = self._sessions.get(session_id)
        if progress is None:
            msg = f"Wave session '{session_id}' not found."
            raise CodingWaveError(msg)

        if progress.is_completed:
            msg = f"Wave session '{session_id}' is already fully completed."
            raise CodingWaveGateError(msg)

        current_stage = progress.current_stage

        # Strict Gate: Verify all tasks in current stage are COMPLETED
        current_stage_tasks = [t for t in progress.tasks if t.stage == current_stage]
        uncompleted = [t for t in current_stage_tasks if t.status != WaveTaskStatusEnum.COMPLETED]
        if uncompleted:
            pending_ids = [t.task_id for t in uncompleted]
            msg = f"Stage gate blocked: tasks {pending_ids} in '{current_stage}' are not completed."
            raise CodingWaveGateError(msg)

        # Determine next stage in sequence
        curr_idx = STAGE_ORDER.index(current_stage)
        if curr_idx >= len(STAGE_ORDER) - 1:
            # Reached final stage (WAVE5_EVAL) completion
            new_progress = dataclasses.replace(
                progress,
                is_completed=True,
                updated_at=datetime.now(tz=UTC),
            )
            self._sessions[session_id] = new_progress
            logger.info("Wave session '%s' successfully reached full pipeline completion", session_id)
            return new_progress

        next_stage = STAGE_ORDER[curr_idx + 1]

        # Transition next stage tasks from PENDING to IN_PROGRESS
        activated_tasks: list[WaveTaskNode] = []
        for task in progress.tasks:
            if task.stage == next_stage and task.status == WaveTaskStatusEnum.PENDING:
                activated_tasks.append(dataclasses.replace(task, status=WaveTaskStatusEnum.IN_PROGRESS))
            else:
                activated_tasks.append(task)

        new_progress = dataclasses.replace(
            progress,
            current_stage=next_stage,
            tasks=tuple(activated_tasks),
            updated_at=datetime.now(tz=UTC),
        )
        self._sessions[session_id] = new_progress
        logger.info("Session '%s' advanced from '%s' to '%s'", session_id, current_stage, next_stage)
        return new_progress

    def export_progress_json(self, session_id: str) -> str:
        """Export session execution state to orchestration_progress.json format."""
        progress = self._sessions.get(session_id)
        if progress is None:
            msg = f"Wave session '{session_id}' not found."
            raise CodingWaveError(msg)

        tasks_payload = [
            {
                "task_id": t.task_id,
                "stage": t.stage.value,
                "title": t.title,
                "role": t.role,
                "model_override": t.model_override,
                "status": t.status.value,
                "output_summary": t.output_summary,
            }
            for t in progress.tasks
        ]

        data = {
            "session_id": progress.session_id,
            "current_stage": progress.current_stage.value,
            "is_completed": progress.is_completed,
            "updated_at": progress.updated_at.isoformat(),
            "tasks": tasks_payload,
        }
        return json.dumps(data, indent=2, ensure_ascii=False)
