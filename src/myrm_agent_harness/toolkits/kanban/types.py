"""Kanban domain types.

Pure data definitions — no I/O, safe to import anywhere.
Consumed by dispatcher, store, tools, and application adapters.

[INPUT]
- (none)

[OUTPUT]
- TaskStatus: Kanban task lifecycle states.
- TaskPriority: Task urgency levels.
- BoardSettings: Tunable board-level knobs.
- KanbanBoard: Top-level grouping entity.
- KanbanTask: Unit of work on a board.
- TaskClaim: Worker ownership record.
- TaskRunOutcome: Outcome classification for a completed run.
- TaskRun: Independent record per execution attempt.
- TaskEventKind: Lifecycle event categories.
- TaskEvent: Persistent lifecycle event.
- TaskTimeoutError: Raised when a task exceeds its max_runtime_seconds.
- KANBAN_SOURCE_CHAT_METADATA_KEY: Metadata key linking tasks to originating chat sessions.
- extract_source_chat_id: Read trimmed source_chat_id from task metadata.
- inherit_source_chat_metadata: Build metadata patch for child task inheritance.

[POS]
Kanban domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

KANBAN_SOURCE_CHAT_METADATA_KEY = "source_chat_id"


def extract_source_chat_id(metadata: dict[str, object] | None) -> str | None:
    """Return trimmed source_chat_id from task metadata, or None."""
    if not metadata:
        return None
    raw = metadata.get(KANBAN_SOURCE_CHAT_METADATA_KEY)
    if not isinstance(raw, str):
        return None
    trimmed = raw.strip()
    return trimmed or None


def inherit_source_chat_metadata(parent_metadata: dict[str, object] | None) -> dict[str, object] | None:
    """Build metadata patch copying source_chat_id from a parent task."""
    source_chat_id = extract_source_chat_id(parent_metadata)
    if source_chat_id is None:
        return None
    return {KANBAN_SOURCE_CHAT_METADATA_KEY: source_chat_id}


class TaskStatus(StrEnum):
    """Kanban task lifecycle states.

    State machine::

        TRIAGE ──► BACKLOG ──► READY ──► RUNNING ──► COMPLETED
           │          │           │          │
           │          │           │          ├──► FAILED
           │          │           │          │
           │          │           │          └──► BLOCKED
           │          │           │
           └──────────┴───────────┴──► ARCHIVED

    TRIAGE is the inbox for rough ideas pending LLM-driven Specifier rewrite.
    A TRIAGE task is opaque to the dispatcher (never claimed) — it can only
    transition to BACKLOG/READY (via specify) or to ARCHIVED (manual discard).
    """

    TRIAGE = "triage"
    BACKLOG = "backlog"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


_TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.ARCHIVED})

_ACTIVE_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.BLOCKED})

# Allowed transitions out of TRIAGE — protects state-machine integrity.
# TRIAGE → BACKLOG (after specify, if deps unmet) / READY (after specify, no deps) /
# ARCHIVED (manual discard). Direct TRIAGE → RUNNING etc. is illegal.
_TRIAGE_ALLOWED_TARGETS: frozenset[TaskStatus] = frozenset({TaskStatus.BACKLOG, TaskStatus.READY, TaskStatus.ARCHIVED})


class BlockKind(StrEnum):
    """Sub-type for BLOCKED tasks — distinguishes *why* a task is blocked.

    HUMAN: waiting for a human decision (e.g. PR review, manual approval).
    SCHEDULED: waiting for a specific time — dispatcher auto-unblocks when due.
    EXTERNAL: waiting for an external event (e.g. CI/CD pipeline, webhook).
    """

    HUMAN = "human"
    SCHEDULED = "scheduled"
    EXTERNAL = "external"


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


_PRIORITY_ORDER: dict[TaskPriority, int] = {
    TaskPriority.URGENT: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.NORMAL: 2,
    TaskPriority.LOW: 3,
}


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskAttachment:
    """Immutable file attachment associated with a kanban task.

    ``content_ref`` is a polymorphic reference supporting:
      - HTTP URL: ``https://host/files/abc``  (sandbox-local access)
      - Vault pointer: ``vault://<uuid>``     (zero-copy large files)
      - Inline data: ``data:image/png;base64,...`` (small previews)
    """

    file_id: str
    filename: str
    mime_type: str
    size_bytes: int
    content_ref: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "content_ref": self.content_ref,
        }


@dataclass(frozen=True, slots=True)
class BoardSettings:
    """Tunable knobs for a KanbanBoard.

    Defaults are conservative — suitable for a personal single-machine setup.

    Specifier knobs:
        specify_max_tokens: hard ceiling on completion tokens for the
            triage→spec LLM call (prevents runaway spend on a single task).
            Mirrors hermes ``HERMES_KANBAN_SPECIFY_MAX_TOKENS`` (default 6000).
        auto_specify_on_create: when True, tasks created with
            ``initial_status=TRIAGE`` are scheduled for an immediate Specifier
            pass without explicit user action. Off by default to keep token
            spend predictable and let users batch-review previews.
    """

    max_concurrent_tasks: int = 3
    heartbeat_interval_seconds: int = 30
    zombie_timeout_seconds: int = 120
    max_retries_per_task: int = 3
    auto_block_after_consecutive_failures: int = 5
    specify_max_tokens: int = 6000
    auto_specify_on_create: bool = False
    default_workdir: str | None = None


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


@dataclass
class KanbanBoard:
    """Top-level grouping entity for kanban tasks."""

    board_id: str
    name: str
    description: str = ""
    settings: BoardSettings = field(default_factory=BoardSettings)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        return {
            "board_id": self.board_id,
            "name": self.name,
            "description": self.description,
            "settings": {
                "max_concurrent_tasks": self.settings.max_concurrent_tasks,
                "heartbeat_interval_seconds": self.settings.heartbeat_interval_seconds,
                "zombie_timeout_seconds": self.settings.zombie_timeout_seconds,
                "max_retries_per_task": self.settings.max_retries_per_task,
                "auto_block_after_consecutive_failures": self.settings.auto_block_after_consecutive_failures,
                "specify_max_tokens": self.settings.specify_max_tokens,
                "auto_specify_on_create": self.settings.auto_specify_on_create,
                "default_workdir": self.settings.default_workdir,
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class KanbanTask:
    """Unit of work on a board."""

    task_id: str
    board_id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.BACKLOG
    priority: TaskPriority = TaskPriority.NORMAL

    # Agent binding — allows different tasks to use different agent profiles
    agent_id: str | None = None

    # Hierarchy — simple parent-child, no complex DAG
    parent_task_id: str | None = None

    # Workspace isolation — per-task git worktree for parallel coding tasks
    workspace_path: str | None = None
    branch: str | None = None

    # Execution tracking
    max_runtime_seconds: int | None = None
    extra_skill_ids: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    consecutive_failures: int = 0
    block_cycle_count: int = 0
    last_heartbeat_at: datetime | None = None
    progress_note: str | None = None
    blocked_reason: str | None = None
    block_kind: BlockKind | None = None
    scheduled_until: datetime | None = None
    result: str = ""
    error: str = ""

    # Attachments — images/documents for multimodal task context
    attachments: list[TaskAttachment] = field(default_factory=list)

    # Metadata
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    @property
    def is_active(self) -> bool:
        return self.status in _ACTIVE_STATUSES

    @property
    def is_retriable(self) -> bool:
        return self.retry_count < self.max_retries

    @property
    def priority_order(self) -> int:
        return _PRIORITY_ORDER.get(self.priority, 2)

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "task_id": self.task_id,
            "board_id": self.board_id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "agent_id": self.agent_id,
            "parent_task_id": self.parent_task_id,
            "workspace_path": self.workspace_path,
            "branch": self.branch,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "consecutive_failures": self.consecutive_failures,
            "block_cycle_count": self.block_cycle_count,
            "max_runtime_seconds": self.max_runtime_seconds,
            "extra_skill_ids": self.extra_skill_ids,
            "blocked_reason": self.blocked_reason,
            "block_kind": self.block_kind.value if self.block_kind else None,
            "scheduled_until": (self.scheduled_until.isoformat() if self.scheduled_until else None),
            "result": self.result,
            "error": self.error,
            "attachments": [a.to_dict() for a in self.attachments],
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": (self.completed_at.isoformat() if self.completed_at else None),
        }
        if self.last_heartbeat_at:
            data["last_heartbeat_at"] = self.last_heartbeat_at.isoformat()
        if self.progress_note:
            data["progress_note"] = self.progress_note
        return data


@dataclass(frozen=True, slots=True)
class TaskEdge:
    """Directed dependency edge: child depends on parent.

    Forms a DAG — cycles are rejected at insertion time via DFS.
    """

    parent_task_id: str
    child_task_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "parent_task_id": self.parent_task_id,
            "child_task_id": self.child_task_id,
        }


@dataclass(frozen=True, slots=True)
class TaskClaim:
    """Worker ownership record for an in-progress task."""

    task_id: str
    worker_id: str
    claimed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Execution history & audit trail
# ---------------------------------------------------------------------------


class TaskRunOutcome(StrEnum):
    """Outcome classification for a completed run."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    CRASHED = "crashed"
    TIMED_OUT = "timed_out"
    RECLAIMED = "reclaimed"


@dataclass
class TaskRun:
    """Independent record per execution attempt.

    Each time the dispatcher claims and executes a task, a new TaskRun
    is created.  This preserves full history across retries: per-run
    duration, error, summary, and worker identity.
    """

    run_id: str
    task_id: str
    worker_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    outcome: TaskRunOutcome | None = None
    summary: str = ""
    error: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def is_finished(self) -> bool:
        return self.outcome is not None

    @property
    def duration_seconds(self) -> float | None:
        if self.ended_at and self.started_at:
            return (self.ended_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "outcome": self.outcome.value if self.outcome else None,
            "summary": self.summary,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "metadata": self.metadata,
        }


class TaskEventKind(StrEnum):
    """Lifecycle event categories."""

    CREATED = "created"
    CLAIMED = "claimed"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
    RETRYING = "retrying"
    RECLAIMED = "reclaimed"
    PROMOTED = "promoted"
    ARCHIVED = "archived"
    HEARTBEAT = "heartbeat"
    USER_COMMENT = "user_comment"
    VERIFICATION_FAILED = "verification_failed"
    BRANCH_SWITCHED = "branch_switched"
    SPECIFIED = "specified"
    DECOMPOSED = "decomposed"
    TIMED_OUT = "timed_out"
    EDITED = "edited"


@dataclass(frozen=True)
class TaskEvent:
    """Persistent lifecycle event for audit and catch-up."""

    event_id: int
    task_id: str
    kind: TaskEventKind
    payload: dict[str, object] | None = None
    run_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "kind": self.kind.value,
            "payload": self.payload,
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class VerificationResult:
    """The outcome of evaluating a single task-completion criterion."""

    passed: bool
    reason: str | None = None
    error_logs: str | None = None


class TaskTimeoutError(Exception):
    """Raised when a task exceeds its max_runtime_seconds.

    Carries elapsed and limit info so the dispatcher can emit a
    TIMED_OUT event with audit-grade payload.
    """

    def __init__(
        self,
        task_id: str,
        elapsed_seconds: float,
        limit_seconds: int,
    ) -> None:
        self.task_id = task_id
        self.elapsed_seconds = elapsed_seconds
        self.limit_seconds = limit_seconds
        super().__init__(f"Task {task_id[:8]} timed out after {elapsed_seconds:.0f}s (limit {limit_seconds}s)")
