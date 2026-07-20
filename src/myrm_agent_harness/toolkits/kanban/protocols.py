"""Protocols for the kanban toolkit.

Five contracts that the application layer must satisfy:

- ``KanbanStore``          — persistence (CRUD + claim + heartbeat + reclaim + runs + events)
- ``TaskRunner``           — execute a claimed task (application layer injects agent logic)
- ``CompletionVerifier``   — verify task completion to prevent hallucinated success
- ``TaskSpecifier``        — rewrite a TRIAGE one-liner into a structured spec via LLM
- ``TaskDecomposer``       — fan a TRIAGE task out into a graph of child tasks via LLM

[INPUT]
- .types::KanbanBoard, KanbanTask, TaskEdge, TaskStatus, TaskRun, TaskRunOutcome,
         TaskEvent, TaskEventKind (POS: Kanban domain types.)
- kanban.types::VerificationResult (POS: Verification result type.)

[OUTPUT]
- KanbanStore: Persistence contract for boards and tasks.
- TaskRunner: Executes a single kanban task.
- CompletionVerifier: Verifies task completion against acceptance criteria.
- TaskSpecifier: Rewrites a TRIAGE task into a structured spec via LLM.
- SpecifyOutcome: Structured result of a single specify pass (no exceptions).
- TaskDecomposer: Fans a TRIAGE task out into a graph of child tasks via LLM.
- DecomposeOutcome: Structured result of a single decompose pass (no exceptions).

[POS]
Protocols for the kanban toolkit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.kanban.types import (
        KanbanBoard,
        KanbanTask,
        TaskEdge,
        TaskEvent,
        TaskEventKind,
        TaskRun,
        TaskRunOutcome,
        TaskStatus,
        VerificationResult,
    )


# ---------------------------------------------------------------------------
# KanbanStore — unified persistence
# ---------------------------------------------------------------------------


@runtime_checkable
class KanbanStore(Protocol):
    """Persistence contract for kanban boards and tasks.

    All datetime values are UTC.  Authorization is handled by the
    service layer — the store itself is auth-agnostic.
    """

    # -- Board CRUD --

    async def get_board(self, board_id: str) -> KanbanBoard | None:
        """Return a board by ID, or None."""
        ...

    async def list_boards(self) -> list[KanbanBoard]:
        """Return all boards."""
        ...

    async def save_board(self, board: KanbanBoard) -> KanbanBoard:
        """Create or update a board (upsert)."""
        ...

    async def delete_board(self, board_id: str) -> bool:
        """Delete a board and all its tasks.  Returns True if deleted."""
        ...

    # -- Task CRUD --

    async def get_task(self, task_id: str) -> KanbanTask | None:
        """Return a task by ID, or None."""
        ...

    async def list_tasks(
        self,
        board_id: str,
        *,
        status: TaskStatus | None = None,
        parent_task_id: str | None = None,
        agent_id: str | None = None,
        source_chat_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[KanbanTask]:
        """Return tasks for a board, optionally filtered by status, parent, agent, or source chat."""
        ...

    async def count_tasks(
        self,
        board_id: str,
        *,
        status: TaskStatus | None = None,
    ) -> int:
        """Count tasks for a board, optionally filtered by status."""
        ...

    async def count_tasks_grouped(
        self,
        board_id: str,
    ) -> dict[str, int]:
        """Count tasks grouped by status. Returns {status_value: count}."""
        ...

    async def save_task(self, task: KanbanTask) -> KanbanTask:
        """Create or update a task (upsert)."""
        ...

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task.  Returns True if deleted."""
        ...

    # -- Dependency edges (DAG) --

    async def add_edge(self, parent_task_id: str, child_task_id: str) -> TaskEdge:
        """Add a dependency edge: child depends on parent.

        Raises ValueError if the edge would create a cycle.
        """
        ...

    async def remove_edge(self, parent_task_id: str, child_task_id: str) -> bool:
        """Remove a dependency edge.  Returns True if removed."""
        ...

    async def list_parents(self, task_id: str) -> list[str]:
        """Return IDs of tasks that *task_id* depends on (upstream)."""
        ...

    async def list_children(self, task_id: str) -> list[str]:
        """Return IDs of tasks that depend on *task_id* (downstream)."""
        ...

    async def are_dependencies_met(self, task_id: str) -> bool:
        """True when all parent tasks are in a terminal status (COMPLETED/FAILED/ARCHIVED)."""
        ...

    # -- Dispatch operations --

    async def claim_task(self, task_id: str, worker_id: str) -> bool:
        """Atomically claim a READY task for a worker.

        Sets status to RUNNING and records the worker_id.
        Returns False if the task is no longer READY (lost race).
        """
        ...

    async def list_ready_tasks(self, board_id: str) -> list[KanbanTask]:
        """Return READY tasks sorted by priority (urgent first), then created_at."""
        ...

    async def list_running_tasks(self, board_id: str) -> list[KanbanTask]:
        """Return all RUNNING tasks for a board."""
        ...

    # -- Heartbeat operations --

    async def update_heartbeat(self, task_id: str, *, note: str | None = None) -> None:
        """Update the last_heartbeat_at timestamp for a running task.

        When *note* is provided, also sets ``progress_note`` on the task.
        """
        ...

    async def list_zombie_tasks(self, board_id: str, timeout_seconds: int) -> list[KanbanTask]:
        """Return RUNNING tasks whose last heartbeat is older than timeout."""
        ...

    async def list_due_scheduled_tasks(self, board_id: str) -> list[KanbanTask]:
        """Return BLOCKED tasks with block_kind=SCHEDULED and scheduled_until <= now."""
        ...

    # -- Run history --

    async def create_run(self, task_id: str, worker_id: str) -> TaskRun:
        """Create a new execution run record when a task is claimed."""
        ...

    async def complete_run(
        self,
        run_id: str,
        outcome: TaskRunOutcome,
        *,
        summary: str = "",
        error: str = "",
    ) -> TaskRun:
        """Mark a run as finished with the given outcome."""
        ...

    async def list_runs(self, task_id: str) -> list[TaskRun]:
        """Return all runs for a task, ordered by started_at ascending."""
        ...

    # -- Event trail --

    async def append_event(
        self,
        task_id: str,
        kind: TaskEventKind,
        *,
        payload: dict[str, object] | None = None,
        run_id: str | None = None,
    ) -> TaskEvent:
        """Persist a lifecycle event."""
        ...

    async def list_events(
        self,
        task_id: str,
        *,
        since_id: int | None = None,
    ) -> list[TaskEvent]:
        """Return events for a task, ordered by event_id ascending.

        If *since_id* is given, only events with event_id > since_id are returned.
        """
        ...


# ---------------------------------------------------------------------------
# TaskRunner — single-task executor
# ---------------------------------------------------------------------------


@runtime_checkable
class TaskRunner(Protocol):
    """Executes a single kanban task.

    The application layer provides a concrete runner that wires up
    SubagentManager, agent configuration, and tool injection.
    """

    async def run(self, task: KanbanTask) -> tuple[bool, str]:
        """Execute a task.

        Returns:
            (success, result_or_error) — True + result text on success,
            False + error message on failure.
        """
        ...


# ---------------------------------------------------------------------------
# CompletionVerifier — hallucination gate
# ---------------------------------------------------------------------------


@runtime_checkable
class CompletionVerifier(Protocol):
    """Verifies task completion to prevent hallucinated success.

    Called by the dispatcher after TaskRunner reports success. If verification
    fails, the task is treated as a failure and retried per the retry budget.

    The application layer decides verification strategy:
    - Tasks with ``metadata["completion_criteria"]``: use configured criteria
    - Tasks with no criteria: skip verification (always pass)
    """

    async def verify(self, task: KanbanTask, result: str) -> VerificationResult:
        """Verify whether a task truly completed its objective.

        Args:
            task: The kanban task that reported success.
            result: The result text returned by the TaskRunner.

        Returns:
            VerificationResult — passed=True if verified, else reason for failure.
        """
        ...


# ---------------------------------------------------------------------------
# TaskSpecifier — TRIAGE → structured spec rewrite via LLM
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpecifyOutcome:
    """Result of a single Specifier pass.

    Mirrors the no-exception contract from hermes ``kanban_specify.SpecifyOutcome``:
    failures (LLM unavailable, malformed reply, parse error, race lost) surface
    via ``ok=False`` so batch sweeps and dry-runs can continue past individual
    failures and still display a useful preview.

    Fields:
        ok: True when the spec was produced and (if ``persisted=True``) saved.
        new_title: tightened title from the LLM, or None if the reply held
            only a body — caller must keep the original title in that case.
        new_body: structured spec body in markdown (Goal / Approach /
            Acceptance criteria / Out of scope), or None on hard failure.
        reason: short machine-friendly classifier
            (``"specified"`` | ``"specifier_unavailable"`` | ``"llm_error:<type>"``
            | ``"parse_failed"`` | ``"empty_response"`` | ``"not_triage"`` |
            ``"race_lost"`` | ``"missing_title_and_body"``).
        prompt_tokens / completion_tokens: usage from the LLM call, if
            reported. Used for SaaS metering and UI cost display.
        persisted: False for dry-runs (preview only), True after Apply.
    """

    task_id: str
    ok: bool
    reason: str = ""
    new_title: str | None = None
    new_body: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    persisted: bool = False


@runtime_checkable
class TaskSpecifier(Protocol):
    """Rewrites a TRIAGE task into a structured, actionable spec via LLM.

    The framework defines the contract; the application layer injects a
    concrete implementation that owns the LLM credentials / prompt template
    / cost accounting. Mirrors hermes ``kanban_specify.specify_task`` but
    is exposed as a Protocol so non-hermes backends (mock, deterministic,
    local-model) can swap in.

    A specifier MUST be idempotent in spirit: calling it twice on the same
    task produces another draft, but never escalates state without an
    explicit Apply (persist=True).
    """

    async def specify(
        self,
        task: KanbanTask,
        *,
        persist: bool = False,
    ) -> SpecifyOutcome:
        """Produce a structured spec for a TRIAGE task.

        Args:
            task: A task in TRIAGE status (callers are responsible for the
                pre-check; the specifier returns ``reason="not_triage"`` if
                violated to keep the contract defensive).
            persist: When False, returns the spec as a preview without
                touching the store (dry-run for the UI Apply/Reject loop).
                When True, the caller has confirmed Apply — the specifier
                still only owns the LLM call; the actual persistence is
                performed by the service layer using the returned outcome.

        Returns:
            SpecifyOutcome — never raises for expected failure modes.
        """
        ...


# ---------------------------------------------------------------------------
# TaskDecomposer — TRIAGE → child task graph via LLM
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecomposeChildSpec:
    """One child task proposed by the LLM decomposer."""

    title: str
    body: str
    assignee: str | None = None
    parent_indices: tuple[int, ...] = ()
    extra_skill_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DecomposeOutcome:
    """Result of a single Decomposer pass.

    Mirrors the no-exception contract from ``SpecifyOutcome``: failures
    surface via ``ok=False`` so batch sweeps and dry-runs can continue past
    individual failures and still display a useful preview.

    Fields:
        ok: True when decomposition produced valid children.
        fanout: True when the LLM proposed multiple children;
            False when it judged the task as a single unit of work.
        children: list of proposed child task specs (populated on fanout=True).
        rationale: short LLM-generated explanation for the decomposition.
        reason: machine-friendly classifier.
        new_title / new_body / new_assignee: populated on fanout=False —
            the LLM's tightened spec for the single task (Specify fallback).
        child_ids: populated after persist — the created task IDs.
        prompt_tokens / completion_tokens: LLM usage for cost display.
        persisted: False for dry-runs, True after Apply.
    """

    task_id: str
    ok: bool
    fanout: bool = False
    children: tuple[DecomposeChildSpec, ...] = ()
    rationale: str = ""
    reason: str = ""
    new_title: str | None = None
    new_body: str | None = None
    new_assignee: str | None = None
    child_ids: tuple[str, ...] = ()
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    persisted: bool = False


@runtime_checkable
class TaskDecomposer(Protocol):
    """Fans a TRIAGE task into a graph of child tasks via LLM.

    The framework defines the contract; the application layer injects a
    concrete implementation that owns the LLM credentials, agent roster,
    and cost accounting.

    A decomposer MUST be idempotent in spirit: calling it twice on the same
    task produces another plan, but never creates children without an
    explicit Apply (persist=True).
    """

    async def decompose(
        self,
        task: KanbanTask,
        *,
        roster: list[dict[str, str]],
        default_assignee: str,
    ) -> DecomposeOutcome:
        """Produce a decomposition plan for a TRIAGE task.

        Args:
            task: A task in TRIAGE status.
            roster: available agent profiles as ``[{name, description}, ...]``.
            default_assignee: fallback agent_id when the LLM picks an
                unknown profile or returns null.

        Returns:
            DecomposeOutcome — never raises for expected failure modes.
        """
        ...
