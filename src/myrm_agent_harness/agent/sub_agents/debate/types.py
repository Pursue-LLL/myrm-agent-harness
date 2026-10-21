"""[INPUT] None.
[OUTPUT] Enum types and data models for Multi-Agent Debate Workroom & Kanban Integration.
[POS] Subagent debate domain types for group collaboration, task decomposition, and kanban sync.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class DebateRole(StrEnum):
    """Specialized roles participating in multi-agent workroom debate."""

    LEADER = "leader"
    RESEARCHER = "researcher"
    CRITIC = "critic"
    IMPLEMENTER = "implementer"
    SYNTHESIZER = "synthesizer"


class DebatePhase(StrEnum):
    """Lifecycle phase of the multi-agent debate workroom."""

    DECOMPOSITION = "decomposition"
    ROUND_ARGUMENT = "round_argument"
    CROSS_EXAMINATION = "cross_examination"
    CONVERGENCE = "convergence"
    SETTLED = "settled"


class DebateSubtaskStatus(StrEnum):
    """Execution status of a decomposed workroom subtask."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    IN_REVIEW = "in_review"
    DONE = "done"


@dataclass
class DebateParticipant:
    """Agent profile metadata inside a debate workroom."""

    agent_id: str
    name: str
    role: DebateRole
    model: str | None = None


@dataclass
class DebateTurn:
    """A single structured speech or cross-examination in the debate stream."""

    turn_id: str
    speaker_id: str
    speaker_name: str
    role: DebateRole
    phase: DebatePhase
    round_index: int
    thesis: str
    counter_points: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    confidence: float = 1.0
    kanban_task_id: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class DebateSubtask:
    """A decomposed actionable subtask linked to the workroom and kanban."""

    task_id: str
    title: str
    description: str
    assigned_agent_id: str
    assigned_role: DebateRole
    status: DebateSubtaskStatus = DebateSubtaskStatus.TODO
    kanban_task_id: str | None = None


@dataclass
class DebateRoomState:
    """Full aggregate state of a multi-agent debate workroom."""

    room_id: str
    chat_id: str
    topic: str
    leader_agent_id: str
    phase: DebatePhase
    round_index: int
    max_rounds: int
    participants: list[DebateParticipant] = field(default_factory=list)
    subtasks: list[DebateSubtask] = field(default_factory=list)
    turns: list[DebateTurn] = field(default_factory=list)
    consensus_decision: str | None = None
    kanban_board_id: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
