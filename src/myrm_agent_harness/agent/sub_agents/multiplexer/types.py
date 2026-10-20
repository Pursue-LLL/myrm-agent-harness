"""Strongly-typed data contracts for Agent Session Multiplexer and cross-agent inspect/instruct.

[INPUT]
- typing::Literal, Mapping
- pydantic::BaseModel, Field

[OUTPUT]
- MultiplexerSessionState: Lifecycle states of multiplexed agent sessions.
- AgentInstruction: Pending or consumed steer/instruct directive between agents.
- MultiplexerSession: Persistent representation of a multiplexed agent session.
- InspectSnapshot: Read-only observational snapshot of a concurrent agent session.
- InstructResult: Result payload of an inject/instruct directive.

[POS]
Data contracts for persistent tmux-style agent multiplexing and cross-agent mutual observation.
"""

from __future__ import annotations

import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

MultiplexerSessionState = Literal[
    "idle",
    "running",
    "waiting_input",
    "blocked",
    "completed",
    "failed",
]


class AgentInstruction(BaseModel):
    """An instruction injected from one agent into another multiplexed session."""

    instruction_id: str = Field(default_factory=lambda: uuid4().hex)
    source_agent: str
    instruction: str
    timestamp: float = Field(default_factory=time.time)
    consumed: bool = False


class MultiplexerSession(BaseModel):
    """Persistent state and descriptors for a multiplexed agent session."""

    session_id: str
    parent_session_id: str | None = None
    agent_type: str
    task_objective: str
    state: MultiplexerSessionState = "idle"
    is_headless: bool = False
    started_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    artifacts: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class InspectSnapshot(BaseModel):
    """Observational inspection snapshot of an agent session for cross-agent visibility."""

    session_id: str
    agent_type: str
    state: MultiplexerSessionState
    is_headless: bool
    task_objective: str
    log_tail: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    pending_instructions_count: int = 0
    snapshot_timestamp: float = Field(default_factory=time.time)


class InstructResult(BaseModel):
    """Outcome of injecting an interactive instruction into a multiplexed session."""

    success: bool
    session_id: str
    instruction_id: str
    message: str
    queued_instructions_count: int
