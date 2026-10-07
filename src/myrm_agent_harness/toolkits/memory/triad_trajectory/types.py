"""Strongly-typed schemas for Task Execution Triad State Trajectory and Blackbox.

[INPUT]
- External: pydantic, datetime, enum

[OUTPUT]
- TriadMilestone: Verified milestone outcome of finished sub-goals.
- TriadFailedAttempt: Dead-end execution failure with actionable anti-loop constraints.
- TriadUserSteering: Dynamic user instruction or constraint introduced in-flight.
- TaskTriadBlackboxTrajectory: Full trajectory container capturing triad history.
- AntiLoopPromptSnapshot: Compact pre-prompt injection payload protecting against loops.

[POS]
Harness framework layer for GPT-6 Astra-inspired long-horizon task triad state management.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TrajectoryTaskStatus(StrEnum):
    """Lifecycle status of a long-horizon task execution."""

    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    HANDOFF_PENDING = "handoff_pending"


class TriadMilestone(BaseModel):
    """Verified milestone outcome representing completed phase of work."""

    milestone_id: str = Field(description="Unique milestone identifier")
    step_index: int = Field(ge=0, description="Step index when milestone was reached")
    title: str = Field(description="Actionable title of completed stage")
    description: str = Field(default="", description="Detailed summary of completed state")
    verified_output_summary: str = Field(description="Evidence or test proof verifying this milestone")
    artifacts_produced: list[str] = Field(default_factory=list, description="Paths or keys of generated artifacts")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Timestamp of completion")


class TriadFailedAttempt(BaseModel):
    """Dead-end path recorded to prevent repetitive loop failures."""

    attempt_id: str = Field(description="Unique failed attempt record ID")
    step_index: int = Field(ge=0, description="Step index when attempt failed")
    action_attempted: str = Field(description="Exact command, tool call, or strategy attempted")
    error_type: str = Field(description="Classification of error (e.g., Timeout, MissingDependency, PortConflict)")
    error_summary: str = Field(description="Concise description of the failure cause")
    dead_end_pattern: str = Field(description="Regex or normalized token sequence matching this dead-end path")
    prohibited_rule: str = Field(description="Explicit actionable instruction prohibiting repetition")
    lessons_learned: str = Field(default="", description="Key guidance on how to avoid this trap")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Timestamp of failure")


class TriadUserSteering(BaseModel):
    """Dynamic steering instruction introduced mid-flight by the user."""

    steering_id: str = Field(description="Unique steering record ID")
    turn_index: int = Field(ge=0, description="Dialogue turn index when steering was issued")
    instruction_raw: str = Field(description="Raw user steering command or constraint text")
    distilled_constraint: str = Field(description="Condensed actionable constraint clause")
    scope: str = Field(default="global", description="Scope of constraint: global, tool_specific, or output_format")
    is_active: bool = Field(default=True, description="Whether constraint is currently active")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Timestamp of user input")


class TaskTriadBlackboxTrajectory(BaseModel):
    """Complete triad blackbox state trajectory for a long-horizon task."""

    task_id: str = Field(description="Unique task identifier")
    session_id: str = Field(description="Conversation session identifier")
    initial_goal: str = Field(description="Original user task prompt or objective")
    status: TrajectoryTaskStatus = Field(default=TrajectoryTaskStatus.RUNNING, description="Task status")
    milestones: list[TriadMilestone] = Field(default_factory=list, description="Verified completed milestones")
    failed_attempts: list[TriadFailedAttempt] = Field(default_factory=list, description="Dead-end failures to avoid")
    user_steerings: list[TriadUserSteering] = Field(default_factory=list, description="Active user constraints")
    version: int = Field(default=1, ge=1, description="Monotonically increasing version counter")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Task launch timestamp")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Last update timestamp")


class AntiLoopPromptSnapshot(BaseModel):
    """Lightweight pre-prompt snapshot injected before each LLM turn to prevent loops."""

    task_id: str = Field(description="Task identifier")
    snapshot_token_estimate: int = Field(description="Estimated token count of this snapshot")
    dead_end_rules_injected: list[str] = Field(default_factory=list, description="Active dead-end rules included")
    active_user_steerings_injected: list[str] = Field(default_factory=list, description="User constraints included")
    latest_milestone_title: str | None = Field(default=None, description="Most recent milestone achieved")
    formatted_prompt_block: str = Field(description="XML/Markdown string to prepend into model prompt")
