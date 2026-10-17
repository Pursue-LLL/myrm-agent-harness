"""Block details (reason, kind, wake-up time) exist only while a task is BLOCKED.

Each way the toolkit takes a task out of BLOCKED pinned here must drop the three fields, whichever store persists the
task: the orchestrator's unblock and cancel tools, a plan revision that removes the task, the store's
status-transition primitive, and a manual reclaim by the dispatcher. A task that is ready again or archived must not
keep a reason or a countdown for a block that no longer exists.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
from myrm_agent_harness.toolkits.kanban.kanban_agent_tools import create_kanban_tools
from myrm_agent_harness.toolkits.kanban.protocols import PlanRevisionSpec, TaskRevisionItem
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import BlockKind, KanbanBoard, KanbanTask, TaskStatus

_REASON = "Waiting for the client's answer"


@pytest.fixture
async def store() -> InMemoryKanbanStore:
    s = InMemoryKanbanStore()
    await s.save_board(KanbanBoard(board_id="b1", name="Board"))
    return s


async def _save_task(
    store: InMemoryKanbanStore,
    task_id: str,
    status: TaskStatus,
    *,
    block_cycle_count: int = 0,
) -> KanbanTask:
    """Persist a task that carries all three block details, whatever its status."""
    return await store.save_task(
        KanbanTask(
            task_id=task_id,
            board_id="b1",
            title=f"Task {task_id}",
            status=status,
            blocked_reason=_REASON,
            block_kind=BlockKind.SCHEDULED,
            scheduled_until=datetime.now(UTC) + timedelta(hours=2),
            block_cycle_count=block_cycle_count,
        )
    )


async def _call_tool(store: InMemoryKanbanStore, name: str, **arguments: str) -> dict[str, dict[str, object]]:
    tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
    tool = next(t for t in tools if t.name == name)
    reply: dict[str, dict[str, object]] = json.loads(await tool.ainvoke(arguments))
    return reply


async def _stored_block_details(
    store: InMemoryKanbanStore, task_id: str
) -> tuple[str | None, BlockKind | None, datetime | None]:
    task = await store.get_task(task_id)
    assert task is not None
    return task.blocked_reason, task.block_kind, task.scheduled_until


def _reply_block_details(reply: dict[str, dict[str, object]]) -> tuple[object, object, object]:
    task = reply["task"]
    return task["blocked_reason"], task["block_kind"], task["scheduled_until"]


class TestOrchestratorUnblock:
    async def test_unblock_to_ready_drops_block_details(self, store: InMemoryKanbanStore) -> None:
        await _save_task(store, "t1", TaskStatus.BLOCKED)

        reply = await _call_tool(store, "kanban_unblock", task_id="t1")

        assert reply["task"]["status"] == "ready"
        assert _reply_block_details(reply) == (None, None, None)
        assert await _stored_block_details(store, "t1") == (None, None, None)

    async def test_unblock_held_by_unfinished_parent_drops_block_details(self, store: InMemoryKanbanStore) -> None:
        parent = await store.save_task(
            KanbanTask(task_id="parent", board_id="b1", title="P", status=TaskStatus.RUNNING)
        )
        await _save_task(store, "t1", TaskStatus.BLOCKED)
        await store.add_edge(parent.task_id, "t1")

        reply = await _call_tool(store, "kanban_unblock", task_id="t1")

        assert reply["task"]["status"] == "backlog"
        assert _reply_block_details(reply) == (None, None, None)
        assert await _stored_block_details(store, "t1") == (None, None, None)

    async def test_unblock_escalated_to_triage_drops_block_details(self, store: InMemoryKanbanStore) -> None:
        await _save_task(store, "t1", TaskStatus.BLOCKED, block_cycle_count=2)

        reply = await _call_tool(store, "kanban_unblock", task_id="t1")

        assert reply["task"]["status"] == "triage"
        assert _reply_block_details(reply) == (None, None, None)
        assert await _stored_block_details(store, "t1") == (None, None, None)


class TestOrchestratorCancel:
    async def test_cancel_blocked_task_drops_block_details(self, store: InMemoryKanbanStore) -> None:
        await _save_task(store, "t1", TaskStatus.BLOCKED)

        reply = await _call_tool(store, "kanban_cancel_task", task_id="t1", reason="no longer needed")

        assert reply["task"]["status"] == "archived"
        assert _reply_block_details(reply) == (None, None, None)
        assert await _stored_block_details(store, "t1") == (None, None, None)


class TestInMemoryStoreExits:
    async def test_plan_removal_drops_block_details(self, store: InMemoryKanbanStore) -> None:
        await _save_task(store, "t1", TaskStatus.BLOCKED)

        outcome = await store.revise_plan(
            PlanRevisionSpec(board_id="b1", task_changes=(TaskRevisionItem(action="remove", task_id="t1"),))
        )

        assert outcome.ok
        removed = await store.get_task("t1")
        assert removed is not None
        assert removed.status is TaskStatus.ARCHIVED
        assert await _stored_block_details(store, "t1") == (None, None, None)

    @pytest.mark.parametrize("target", [TaskStatus.READY, TaskStatus.ARCHIVED, TaskStatus.FAILED])
    async def test_transition_out_of_blocked_drops_block_details(
        self, store: InMemoryKanbanStore, target: TaskStatus
    ) -> None:
        await _save_task(store, "t1", TaskStatus.BLOCKED)

        moved = await store.transition_task_status("t1", TaskStatus.BLOCKED, target)

        assert moved is not None
        assert (moved.blocked_reason, moved.block_kind, moved.scheduled_until) == (None, None, None)
        assert await _stored_block_details(store, "t1") == (None, None, None)

    async def test_transition_into_blocked_keeps_block_details(self, store: InMemoryKanbanStore) -> None:
        await _save_task(store, "t1", TaskStatus.RUNNING)

        moved = await store.transition_task_status("t1", TaskStatus.RUNNING, TaskStatus.BLOCKED)

        assert moved is not None
        assert moved.status is TaskStatus.BLOCKED
        assert (moved.blocked_reason, moved.block_kind) == (_REASON, BlockKind.SCHEDULED)
        assert moved.scheduled_until is not None


class TestDispatcherManualReclaim:
    async def test_reclaiming_a_task_that_blocked_itself_mid_run_drops_block_details(
        self, store: InMemoryKanbanStore
    ) -> None:
        started = asyncio.Event()

        class _BlockingRunner:
            async def run(self, task: KanbanTask) -> tuple[bool, str]:
                started.set()
                await asyncio.sleep(60)
                return True, "done"

        board = await store.get_board("b1")
        assert board is not None
        await store.save_task(KanbanTask(task_id="t1", board_id="b1", title="Task t1", status=TaskStatus.READY))
        dispatcher = KanbanDispatcher(store, _BlockingRunner(), board)
        await dispatcher.start()
        try:
            await started.wait()
            # The worker's kanban_block call blocks the task while its run is still executing.
            await _save_task(store, "t1", TaskStatus.BLOCKED)

            assert await dispatcher.reclaim_task("t1") is True

            assert await _stored_block_details(store, "t1") == (None, None, None)
        finally:
            await dispatcher.stop()
