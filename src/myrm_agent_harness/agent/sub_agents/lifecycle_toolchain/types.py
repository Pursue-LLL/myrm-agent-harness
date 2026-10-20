"""myrm_agent_harness/agent/sub_agents/lifecycle_toolchain/types.py

[INPUT]
- enum
- uuid
- dataclasses
- datetime

[OUTPUT]
- SubagentStatusEnum
- SubagentLifecycleError
- SubagentNotFoundError
- SubagentTimeoutError
- SubagentInputMessage
- SubagentEventItem
- SubagentTaskRecord
- SubagentSpawnRequest
- SubagentWaitResult

[POS]
myrm_agent_harness/agent/sub_agents/lifecycle_toolchain/types.py
"""

import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


class SubagentStatusEnum(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"
    TIMEOUT = "timeout"


class SubagentLifecycleError(Exception):
    """Base exception for subagent lifecycle failures."""


class SubagentNotFoundError(SubagentLifecycleError):
    """Raised when the specified subagent ID does not exist."""


class SubagentTimeoutError(SubagentLifecycleError):
    """Raised when subagent execution or wait operation times out."""


@dataclass
class SubagentInputMessage:
    message_id: str
    subagent_id: str
    content: str
    sender_role: str
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass
class SubagentEventItem:
    event_id: str
    event_type: str
    subagent_id: str
    payload: dict[str, str | int | float | bool]
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass
class SubagentTaskRecord:
    subagent_id: str
    parent_session_id: str
    task_prompt: str
    agent_profile: str
    tools_whitelist: list[str]
    status: SubagentStatusEnum
    timeout_seconds: float
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    started_at: str | None = None
    ended_at: str | None = None
    result_summary: str | None = None
    error_detail: str | None = None
    kill_reason: str | None = None
    token_usage: int = 0
    step_count: int = 0
    input_queue: list[SubagentInputMessage] = field(default_factory=list)
    events: list[SubagentEventItem] = field(default_factory=list)

    def is_terminal(self) -> bool:
        return self.status in {
            SubagentStatusEnum.COMPLETED,
            SubagentStatusEnum.FAILED,
            SubagentStatusEnum.KILLED,
            SubagentStatusEnum.TIMEOUT,
        }


@dataclass
class SubagentSpawnRequest:
    task_prompt: str
    parent_session_id: str
    agent_profile: str = "general_worker"
    tools_whitelist: list[str] = field(default_factory=list)
    timeout_seconds: float = 60.0
    subagent_id: str = field(
        default_factory=lambda: f"subagent-{uuid.uuid4().hex[:12]}"
    )


@dataclass
class SubagentWaitResult:
    all_completed: bool
    completed_count: int
    failed_count: int
    killed_count: int
    timeout_count: int
    tasks: list[SubagentTaskRecord]
