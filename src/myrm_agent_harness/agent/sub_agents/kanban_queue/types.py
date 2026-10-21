"""Types and data structures for Persistent Kanban Job Queue & Massive Parallel Dogfooding Runner Suite.

[INPUT]
- dataclasses
- enum
- time

[OUTPUT]
- KanbanJobStatus
- SwarmTopologyStage
- JobPriority
- KanbanComment
- KanbanJob
- BlackboardEntry
- TrajectoryRecord
- BatchRunnerConfig

[POS]
Types and data structures for Persistent Kanban Job Queue & Massive Parallel Dogfooding Runner Suite.

"""

from dataclasses import dataclass, field
from enum import Enum
import time


class KanbanJobStatus(str, Enum):
    """5-State lifecycle for persistent kanban jobs + blocked state."""

    TRIAGE = "triage"
    TODO = "todo"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    BLOCKED = "blocked"


class SwarmTopologyStage(str, Enum):
    """Swarm 4-stage topology."""

    PLANNING_ROOT = "planning_root"
    PARALLEL_SPECIALIST = "parallel_specialist"
    VERIFIER_GATE = "verifier_gate"
    SYNTHESIZER = "synthesizer"


class JobPriority(str, Enum):
    """Priority levels for kanban jobs."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class KanbanComment:
    """Comment on a kanban job."""

    author: str
    content: str
    timestamp: float = field(default_factory=time.time)
    is_blackboard: bool = False


@dataclass
class KanbanJob:
    """Persistent Kanban Job entity."""

    job_id: str
    title: str
    goal: str
    approach: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    status: KanbanJobStatus = KanbanJobStatus.TRIAGE
    priority: JobPriority = JobPriority.NORMAL
    stage: SwarmTopologyStage = SwarmTopologyStage.PARALLEL_SPECIALIST
    assignee: str | None = None
    dependencies: list[str] = field(default_factory=list)
    blocked_reason: str | None = None
    worktree_path: str | None = None
    container_image: str | None = None
    skills: list[str] = field(default_factory=list)
    comments: list[KanbanComment] = field(default_factory=list)
    result_summary: str | None = None
    result_metadata: dict[str, str] = field(default_factory=dict)
    last_heartbeat_timestamp: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    failure_count: int = 0
    goal_mode: bool = False
    goal_max_turns: int = 15


@dataclass
class BlackboardEntry:
    """Structured JSON entry on the Swarm shared blackboard."""

    entry_id: str
    job_id: str
    stage: SwarmTopologyStage
    author: str
    payload: dict[str, str]
    created_at: float = field(default_factory=time.time)


@dataclass
class TrajectoryRecord:
    """HuggingFace compatible trajectory record for training/eval."""

    task_id: str
    prompt: str
    tool_calls: list[dict[str, str]] = field(default_factory=list)
    tool_usage_stats: dict[str, int] = field(default_factory=dict)
    final_response: str = ""
    turns_taken: int = 0
    success: bool = True
    timestamp: float = field(default_factory=time.time)


@dataclass
class BatchRunnerConfig:
    """Config for 12-way massive parallel dogfooding runner."""

    max_parallel: int = 12
    distribution_strategy: str = "round_robin"
    resume_checkpoint: bool = True
    stale_timeout_seconds: float = 14400.0  # 4 hours
