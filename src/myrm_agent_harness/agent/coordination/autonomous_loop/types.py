"""Domain types and contracts for Goal-Driven Autonomous Orchestration Loop (Item 38).

[INPUT]
- Session identifiers, goal definitions, orchestration modes, and loop step events.

[OUTPUT]
- Strongly-typed domain models for autonomous orchestration modes, loop states,
  step histories, and safety watchdog configurations.

[POS]
- Harness coordination layer contracts for multi-step autonomous execution and supervision.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


class OrchestrationMode(enum.StrEnum):
    """Operational mode of the multi-agent orchestrator loop."""

    AUTONOMOUS = "autonomous"
    SUPERVISED = "supervised"
    PAUSED = "paused"
    COMPLETED = "completed"


class StepStatus(enum.StrEnum):
    """Execution status of an individual autonomous loop step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass(frozen=True)
class AutonomousLoopConfig:
    """Safety watchdog constraints and pacing configuration for autonomous loops."""

    max_autonomous_steps: int = 10
    pause_on_approval: bool = True
    pause_on_error: bool = True
    heartbeat_interval_s: float = 1.0


@dataclass(frozen=True)
class AutonomousLoopStep:
    """Record of a single autonomously advanced action or heartbeat step."""

    step_index: int
    action_type: str
    description: str
    status: StepStatus = StepStatus.SUCCESS
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class AutonomousLoopState:
    """Real-time consolidated state of an orchestrated autonomous loop."""

    session_id: str
    goal_id: str
    mode: OrchestrationMode
    current_step: int
    max_steps: int
    is_active: bool
    history: list[AutonomousLoopStep] = field(default_factory=list)
    pause_reason: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    last_advanced_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
