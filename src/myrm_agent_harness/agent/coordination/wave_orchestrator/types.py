"""Domain types and contracts for Coding Agent Wave Preset Orchestrator (Item 45).

[INPUT]
- Wave stage definitions, role-to-model routing configurations, task node status,
  and orchestration progression telemetry.

[OUTPUT]
- Strongly-typed models: WaveStageEnum, WaveTaskStatusEnum, WaveTaskNode,
  WavePresetConfig, WaveExecutionProgress.

[POS]
- Harness coordination layer contracts for optional coding agent wave pipeline.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


class WaveStageEnum(enum.StrEnum):
    """Discrete phases of the full-stack development wave pipeline."""

    PLANNING = "planning"
    WAVE1_DEV = "wave1_dev"
    WAVE2_REVIEW = "wave2_review"
    WAVE3_TEST = "wave3_test"
    WAVE4_VISUAL = "wave4_visual"
    WAVE5_EVAL = "wave5_eval"


class WaveTaskStatusEnum(enum.StrEnum):
    """Lifecycle state of an individual wave subtask node."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class WaveTaskNode:
    """Individual task unit assigned to a specific role and execution model in a wave."""

    task_id: str
    stage: WaveStageEnum
    title: str
    role: str
    model_override: str | None = None
    status: WaveTaskStatusEnum = WaveTaskStatusEnum.PENDING
    output_summary: str | None = None


@dataclass(frozen=True)
class WavePresetConfig:
    """Preset configuration specification for the full-stack coding wave pipeline."""

    preset_id: str = "full-stack-dev-wave"
    name: str = "Full-Stack Development Wave Pipeline"
    description: str = (
        "Structured multi-wave software engineering pipeline dividing complex features into "
        "cloud planning (Kimi K3), parallel coding (local/MoE Ornith), GLM review, and automated QA."
    )
    role_model_routing: dict[str, str] = field(
        default_factory=lambda: {
            "tech-lead": "kimi-k3",
            "backend-dev": "ornith-1.5",
            "frontend-dev": "kimi-k3",
            "code-reviewer": "glm-5.3",
            "qa-tester": "ornith-1.5",
            "acceptance-eval": "kimi-k3",
        }
    )


@dataclass(frozen=True)
class WaveExecutionProgress:
    """Execution state and progression ledger of a coding wave session."""

    session_id: str
    current_stage: WaveStageEnum
    tasks: tuple[WaveTaskNode, ...]
    is_completed: bool = False
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
