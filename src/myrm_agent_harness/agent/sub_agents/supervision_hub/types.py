"""Type definitions and contracts for Subagent Supervision Hub.

[INPUT]
- None (pure domain types)

[OUTPUT]
- SubagentWorkerStatus, SupervisionTranscriptEntry, SubagentWorkerRosterItem
- SubagentRosterOverview, SupervisionActionType, SupervisionActionResult

[POS]
myrm_agent_harness/agent/sub_agents/supervision_hub/types.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

SubagentWorkerStatus = Literal[
    "running",
    "parked",
    "stuck",
    "done",
    "failed",
    "interrupted",
]

SupervisionActionType = Literal[
    "steer",
    "kill",
    "revive",
]


@dataclass(slots=True)
class SupervisionTranscriptEntry:
    """A single trace entry in a worker's live transcript."""

    entry_id: str
    timestamp: str
    tool_name: str
    input_summary: str
    output_summary: str
    level: Literal["info", "warn", "error"] = "info"
    duration_ms: int | None = None


@dataclass(slots=True)
class SubagentWorkerRosterItem:
    """Status and activity metrics for an individual subagent worker."""

    task_id: str
    agent_type: str
    status: SubagentWorkerStatus
    current_activity: str
    model: str = "default"
    tokens_used: int = 0
    elapsed_seconds: float = 0.0
    last_tool: str = ""
    can_steer: bool = True
    can_kill: bool = True
    can_revive: bool = False
    description: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(slots=True)
class SubagentRosterOverview:
    """Aggregated roster summary for a parent chat session."""

    session_id: str
    total_workers: int
    active_workers: int
    parked_workers: int
    stuck_workers: int
    total_tokens: int
    total_duration_seconds: float
    workers: list[SubagentWorkerRosterItem] = field(default_factory=list)


@dataclass(slots=True)
class SupervisionActionResult:
    """Outcome of a supervision action (steer, kill, or revive)."""

    task_id: str
    action: SupervisionActionType
    success: bool
    message: str
    new_status: SubagentWorkerStatus
