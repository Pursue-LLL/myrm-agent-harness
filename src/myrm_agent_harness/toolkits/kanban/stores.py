"""In-memory KanbanStore implementation.

Used for testing and as a reference for persistence adapters.

[INPUT]
- .types::KanbanBoard, KanbanTask, TaskEdge, TaskStatus, TaskRun, TaskRunOutcome,
         TaskEvent, TaskEventKind (POS: Kanban domain types.)
- .protocols::KanbanStore (POS: Protocols for the kanban toolkit.)

[OUTPUT]
- InMemoryKanbanStore: Non-persistent reference implementation.

[POS]
In-memory KanbanStore implementation.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.kanban.protocols import (
    KanbanStore,
    PlanRevisionOutcome,
    PlanRevisionSpec,
)
from myrm_agent_harness.toolkits.kanban.types import (
    _PRIORITY_ORDER,
    _TERMINAL_STATUSES,
    KANBAN_SOURCE_CHAT_METADATA_KEY,
    BlockKind,
    KanbanBoard,
    KanbanTask,
    TaskEdge,
    TaskEvent,
    TaskEventKind,
    TaskPriority,
    TaskRun,
    TaskRunOutcome,
    TaskStatus,
)


class InMemoryKanbanStore(KanbanStore):
    """Non-persistent reference implementation.

    Thread-safety: not guaranteed — intended for single-process tests.
    Production deployments must use SqlAlchemyKanbanStore.
    """

    def __init__(self) -> None:
        self._boards: dict[str, KanbanBoard] = {}
        self._tasks: dict[str, KanbanTask] = {}
        self._runs: dict[str, TaskRun] = {}
        self._events: list[TaskEvent] = []
        self._event_seq: int = 0
        self._edges: list[TaskEdge] = []

    def _purge_task_data(self, task_id: str) -> None:
        """Remove runs, events, and edges associated with a task."""
        run_ids = [r_id for r_id, r in self._runs.items() if r.task_id == task_id]
        for r_id in run_ids:
            del self._runs[r_id]
        self._events = [e for e in self._events if e.task_id != task_id]
        self._edges = [e for e in self._edges if e.parent_task_id != task_id and e.child_task_id != task_id]

    # -- Board CRUD --

    async def get_board(self, board_id: str) -> KanbanBoard | None:
        board = self._boards.get(board_id)
        return copy.deepcopy(board) if board else None

    async def list_boards(self) -> list[KanbanBoard]:
        return [copy.deepcopy(b) for b in self._boards.values()]

    async def save_board(self, board: KanbanBoard) -> KanbanBoard:
        board.updated_at = datetime.now(UTC)
        self._boards[board.board_id] = copy.deepcopy(board)
        return board

    async def delete_board(self, board_id: str) -> bool:
        if board_id not in self._boards:
            return False
        del self._boards[board_id]
        to_remove = [t_id for t_id, t in self._tasks.items() if t.board_id == board_id]
        for t_id in to_remove:
            self._purge_task_data(t_id)
            del self._tasks[t_id]
        return True

    # -- Task CRUD --

    async def get_task(self, task_id: str) -> KanbanTask | None:
        task = self._tasks.get(task_id)
        return copy.deepcopy(task) if task else None

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
        results = [t for t in self._tasks.values() if t.board_id == board_id]
        if status is not None:
            results = [t for t in results if t.status == status]
        if parent_task_id is not None:
            results = [t for t in results if t.parent_task_id == parent_task_id]
        if agent_id is not None:
            results = [t for t in results if t.agent_id == agent_id]
        if source_chat_id is not None:
            results = [
                t
                for t in results
                if isinstance(t.metadata, dict) and t.metadata.get(KANBAN_SOURCE_CHAT_METADATA_KEY) == source_chat_id
            ]
        results.sort(key=lambda t: t.created_at)
        results = results[offset:]
        if limit is not None:
            results = results[:limit]
        return [copy.deepcopy(t) for t in results]

    async def count_tasks(
        self,
        board_id: str,
        *,
        status: TaskStatus | None = None,
    ) -> int:
        count = 0
        for t in self._tasks.values():
            if t.board_id != board_id:
                continue
            if status is not None and t.status != status:
                continue
            count += 1
        return count

    async def count_tasks_grouped(self, board_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in self._tasks.values():
            if t.board_id == board_id:
                key = t.status.value
                counts[key] = counts.get(key, 0) + 1
        return counts

    async def save_task(self, task: KanbanTask) -> KanbanTask:
        task.updated_at = datetime.now(UTC)
        self._tasks[task.task_id] = copy.deepcopy(task)
        return task

    async def delete_task(self, task_id: str) -> bool:
        if task_id not in self._tasks:
            return False
        self._purge_task_data(task_id)
        del self._tasks[task_id]
        return True

    # -- Dependency edges (DAG) --

    def _would_create_cycle(self, parent_id: str, child_id: str) -> bool:
        """DFS from parent_id following reverse edges to detect if child_id is reachable."""
        if parent_id == child_id:
            return True
        adj: dict[str, list[str]] = {}
        for e in self._edges:
            adj.setdefault(e.child_task_id, []).append(e.parent_task_id)
        visited: set[str] = set()
        stack = [parent_id]
        while stack:
            node = stack.pop()
            if node == child_id:
                return True
            if node in visited:
                continue
            visited.add(node)
            stack.extend(adj.get(node, []))
        return False

    async def add_edge(self, parent_task_id: str, child_task_id: str) -> TaskEdge:
        if self._would_create_cycle(parent_task_id, child_task_id):
            raise ValueError(f"Adding edge {parent_task_id} -> {child_task_id} would create a cycle")
        for e in self._edges:
            if e.parent_task_id == parent_task_id and e.child_task_id == child_task_id:
                return e
        edge = TaskEdge(parent_task_id=parent_task_id, child_task_id=child_task_id)
        self._edges.append(edge)
        return edge

    async def remove_edge(self, parent_task_id: str, child_task_id: str) -> bool:
        before = len(self._edges)
        self._edges = [
            e for e in self._edges if not (e.parent_task_id == parent_task_id and e.child_task_id == child_task_id)
        ]
        return len(self._edges) < before

    async def list_parents(self, task_id: str) -> list[str]:
        return [e.parent_task_id for e in self._edges if e.child_task_id == task_id]

    async def list_children(self, task_id: str) -> list[str]:
        return [e.child_task_id for e in self._edges if e.parent_task_id == task_id]

    async def are_dependencies_met(self, task_id: str) -> bool:
        parent_ids = [e.parent_task_id for e in self._edges if e.child_task_id == task_id]
        if not parent_ids:
            return True
        for pid in parent_ids:
            parent = self._tasks.get(pid)
            if parent is None or parent.status not in _TERMINAL_STATUSES:
                return False
        return True

    async def revise_plan(self, spec: PlanRevisionSpec) -> PlanRevisionOutcome:
        """Atomically apply plan revision in-memory with cycle & completed-task protection."""
        # 1. Validate completed task immutability
        for item in spec.task_changes:
            if item.action in ("remove", "update") and item.task_id:
                existing = self._tasks.get(item.task_id)
                if existing and existing.status in (TaskStatus.COMPLETED, TaskStatus.IN_REVIEW):
                    return PlanRevisionOutcome(
                        ok=False,
                        board_id=spec.board_id,
                        reason=f"Cannot modify task {item.task_id} in {existing.status.value} status",
                    )

        # 2. Build shadow edges and test for cycles
        shadow_edges = list(self._edges)
        for p_id, c_id in spec.remove_edges:
            shadow_edges = [e for e in shadow_edges if not (e.parent_task_id == p_id and e.child_task_id == c_id)]

        # If a task is removed, remove all incident edges
        removed_task_ids_set = {
            item.task_id for item in spec.task_changes if item.action == "remove" and item.task_id
        }
        if removed_task_ids_set:
            shadow_edges = [
                e
                for e in shadow_edges
                if e.parent_task_id not in removed_task_ids_set and e.child_task_id not in removed_task_ids_set
            ]

        # Add proposed edges
        for p_id, c_id in spec.add_edges:
            if (p_id, c_id) not in [(e.parent_task_id, e.child_task_id) for e in shadow_edges]:
                shadow_edges.append(TaskEdge(parent_task_id=p_id, child_task_id=c_id))

        # Check cycle on shadow edges
        adj: dict[str, list[str]] = {}
        for e in shadow_edges:
            adj.setdefault(e.child_task_id, []).append(e.parent_task_id)

        def _has_cycle() -> bool:
            visited: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited
            all_nodes = set(adj.keys())
            for parents in adj.values():
                all_nodes.update(parents)

            def dfs(node: str) -> bool:
                visited[node] = 1
                for neighbor in adj.get(node, []):
                    if visited.get(neighbor, 0) == 1:
                        return True
                    if visited.get(neighbor, 0) == 0 and dfs(neighbor):
                        return True
                visited[node] = 2
                return False

            for n in all_nodes:
                if visited.get(n, 0) == 0:
                    if dfs(n):
                        return True
            return False

        if _has_cycle():
            return PlanRevisionOutcome(
                ok=False,
                board_id=spec.board_id,
                reason="Plan revision would create a dependency cycle",
            )

        # 3. Apply changes atomically
        added_tids: list[str] = []
        updated_tids: list[str] = []
        removed_tids: list[str] = []

        for item in spec.task_changes:
            if item.action == "add":
                tid = item.task_id or uuid.uuid4().hex[:12]
                try:
                    prio = TaskPriority(item.priority)
                except ValueError:
                    prio = TaskPriority.NORMAL
                deps = list(item.depends_on)
                initial_status = TaskStatus.BACKLOG if deps else TaskStatus.READY
                new_task = KanbanTask(
                    task_id=tid,
                    board_id=spec.board_id,
                    title=item.title or "Untitled Task",
                    description=item.description or "",
                    status=initial_status,
                    priority=prio,
                    agent_id=item.agent_id,
                    model_override=item.model_override,
                    extra_skill_ids=list(item.extra_skill_ids),
                )
                self._tasks[tid] = new_task
                added_tids.append(tid)
                for pid in deps:
                    shadow_edges.append(TaskEdge(parent_task_id=pid, child_task_id=tid))
            elif item.action == "update" and item.task_id:
                t = self._tasks.get(item.task_id)
                if t:
                    if item.title is not None:
                        t.title = item.title
                    if item.description is not None:
                        t.description = item.description
                    if item.agent_id is not None:
                        t.agent_id = item.agent_id
                    if item.model_override is not None:
                        t.model_override = item.model_override
                    if item.extra_skill_ids:
                        t.extra_skill_ids = list(item.extra_skill_ids)
                    t.updated_at = datetime.now(UTC)
                    updated_tids.append(t.task_id)
            elif item.action == "remove" and item.task_id:
                t = self._tasks.get(item.task_id)
                if t:
                    t.status = TaskStatus.ARCHIVED
                    t.completed_at = datetime.now(UTC)
                    t.updated_at = datetime.now(UTC)
                    removed_tids.append(t.task_id)

        # Update edges
        self._edges = shadow_edges

        # Append audit event
        for tid in added_tids + updated_tids + removed_tids:
            await self.append_event(
                tid,
                TaskEventKind.PLAN_REVISED,
                payload={
                    "board_id": spec.board_id,
                    "rationale": spec.rationale,
                    "author": spec.author,
                    "added_count": len(added_tids),
                    "updated_count": len(updated_tids),
                    "removed_count": len(removed_tids),
                },
            )

        return PlanRevisionOutcome(
            ok=True,
            board_id=spec.board_id,
            reason="applied",
            added_task_ids=tuple(added_tids),
            updated_task_ids=tuple(updated_tids),
            removed_task_ids=tuple(removed_tids),
            added_edges=tuple(spec.add_edges),
            removed_edges=tuple(spec.remove_edges),
            persisted=True,
        )

    # -- Dispatch operations --

    async def claim_task(self, task_id: str, worker_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.READY:
            return False
        task.status = TaskStatus.RUNNING
        task.last_heartbeat_at = datetime.now(UTC)
        task.updated_at = datetime.now(UTC)
        task.metadata["worker_id"] = worker_id
        return True

    async def transition_task_status(
        self,
        task_id: str,
        expected_status: TaskStatus,
        new_status: TaskStatus,
    ) -> KanbanTask | None:
        task = self._tasks.get(task_id)
        if task is None or task.status != expected_status:
            return None
        task.status = new_status
        task.updated_at = datetime.now(UTC)
        return copy.deepcopy(task)

    async def list_ready_tasks(self, board_id: str) -> list[KanbanTask]:
        ready = [t for t in self._tasks.values() if t.board_id == board_id and t.status == TaskStatus.READY]
        ready.sort(key=lambda t: (_PRIORITY_ORDER.get(t.priority, 2), t.created_at))
        return [copy.deepcopy(t) for t in ready]

    async def list_running_tasks(self, board_id: str) -> list[KanbanTask]:
        return [
            copy.deepcopy(t) for t in self._tasks.values() if t.board_id == board_id and t.status == TaskStatus.RUNNING
        ]

    # -- Heartbeat operations --

    async def update_heartbeat(self, task_id: str, *, note: str | None = None) -> None:
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.RUNNING:
            task.last_heartbeat_at = datetime.now(UTC)
            if note is not None:
                task.progress_note = note

    async def list_zombie_tasks(self, board_id: str, timeout_seconds: int) -> list[KanbanTask]:
        now = datetime.now(UTC)
        zombies: list[KanbanTask] = []
        for t in self._tasks.values():
            if t.board_id != board_id or t.status != TaskStatus.RUNNING:
                continue
            if t.last_heartbeat_at is None:
                zombies.append(copy.deepcopy(t))
                continue
            elapsed = (now - t.last_heartbeat_at).total_seconds()
            if elapsed > timeout_seconds:
                zombies.append(copy.deepcopy(t))
        return zombies

    async def list_due_scheduled_tasks(self, board_id: str) -> list[KanbanTask]:
        now = datetime.now(UTC)
        return [
            copy.deepcopy(t)
            for t in self._tasks.values()
            if t.board_id == board_id
            and t.status == TaskStatus.BLOCKED
            and t.block_kind == BlockKind.SCHEDULED
            and t.scheduled_until is not None
            and t.scheduled_until <= now
        ]

    # -- Run history --

    async def create_run(self, task_id: str, worker_id: str) -> TaskRun:
        run = TaskRun(
            run_id=uuid.uuid4().hex[:12],
            task_id=task_id,
            worker_id=worker_id,
        )
        self._runs[run.run_id] = run
        return copy.deepcopy(run)

    async def complete_run(
        self,
        run_id: str,
        outcome: TaskRunOutcome,
        *,
        summary: str = "",
        error: str = "",
        token_usage: dict[str, int] | None = None,
        cost_usd: float | None = None,
    ) -> TaskRun:
        run = self._runs.get(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        run.ended_at = datetime.now(UTC)
        run.outcome = outcome
        run.summary = summary
        run.error = error
        if token_usage is not None:
            run.token_usage = token_usage
        if cost_usd is not None:
            run.cost_usd = cost_usd
        return copy.deepcopy(run)

    async def list_runs(self, task_id: str) -> list[TaskRun]:
        runs = [r for r in self._runs.values() if r.task_id == task_id]
        runs.sort(key=lambda r: r.started_at)
        return [copy.deepcopy(r) for r in runs]

    # -- Event trail --

    async def append_event(
        self,
        task_id: str,
        kind: TaskEventKind,
        *,
        payload: dict[str, object] | None = None,
        run_id: str | None = None,
    ) -> TaskEvent:
        self._event_seq += 1
        event = TaskEvent(
            event_id=self._event_seq,
            task_id=task_id,
            kind=kind,
            payload=payload,
            run_id=run_id,
        )
        self._events.append(event)
        return event

    async def list_events(
        self,
        task_id: str,
        *,
        since_id: int | None = None,
    ) -> list[TaskEvent]:
        return [e for e in self._events if e.task_id == task_id and (since_id is None or e.event_id > since_id)]
