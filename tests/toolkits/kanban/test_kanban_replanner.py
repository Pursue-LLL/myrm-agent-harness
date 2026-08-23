"""Tests for Formal Replanner (DAG Revision) in KanbanStore and orchestrator tools."""

from __future__ import annotations

import json
import pytest

from myrm_agent_harness.toolkits.kanban.protocols import (
    PlanRevisionOutcome,
    PlanRevisionSpec,
    TaskRevisionItem,
)
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    KanbanBoard,
    KanbanTask,
    TaskEventKind,
    TaskPriority,
    TaskStatus,
)
from myrm_agent_harness.toolkits.kanban._orchestrator_tools import (
    build_orchestrator_tools,
)


@pytest.fixture
def store() -> InMemoryKanbanStore:
    return InMemoryKanbanStore()


@pytest.fixture
async def board(store: InMemoryKanbanStore) -> KanbanBoard:
    b = KanbanBoard(board_id="b_replan", name="Replan Board")
    return await store.save_board(b)


async def _create_task(
    store: InMemoryKanbanStore,
    task_id: str,
    board_id: str = "b_replan",
    status: TaskStatus = TaskStatus.READY,
) -> KanbanTask:
    task = KanbanTask(
        task_id=task_id,
        board_id=board_id,
        title=f"Task {task_id}",
        status=status,
        priority=TaskPriority.NORMAL,
    )
    return await store.save_task(task)


class TestReplanStore:
    async def test_atomic_add_and_update(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        t1 = await _create_task(store, "t1")
        spec = PlanRevisionSpec(
            board_id="b_replan",
            rationale="Add downstream verification step",
            task_changes=(
                TaskRevisionItem(
                    action="add",
                    task_id="t2",
                    title="Verify Output",
                    description="Run assertion suite",
                    depends_on=("t1",),
                ),
                TaskRevisionItem(
                    action="update",
                    task_id="t1",
                    title="Task 1 Updated",
                ),
            ),
            add_edges=(("t1", "t2"),),
        )

        outcome = await store.revise_plan(spec)
        assert outcome.ok is True
        assert "t2" in outcome.added_task_ids
        assert "t1" in outcome.updated_task_ids

        # Verify task state
        t2 = await store.get_task("t2")
        assert t2 is not None
        assert t2.title == "Verify Output"
        assert t2.status == TaskStatus.BACKLOG

        t1_updated = await store.get_task("t1")
        assert t1_updated is not None
        assert t1_updated.title == "Task 1 Updated"

        # Verify edge
        children = await store.list_children("t1")
        assert "t2" in children

        # Verify audit event
        events = await store.list_events("t2")
        assert any(e.kind == TaskEventKind.PLAN_REVISED for e in events)

    async def test_completed_task_protection(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "t_done", status=TaskStatus.COMPLETED)
        spec = PlanRevisionSpec(
            board_id="b_replan",
            rationale="Illegal tamper attempt",
            task_changes=(
                TaskRevisionItem(
                    action="remove",
                    task_id="t_done",
                ),
            ),
        )
        outcome = await store.revise_plan(spec)
        assert outcome.ok is False
        assert "Cannot modify task" in outcome.reason

        # Ensure task still exists and untouched
        t_done = await store.get_task("t_done")
        assert t_done is not None
        assert t_done.status == TaskStatus.COMPLETED

    async def test_cycle_rejection(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "node_a")
        await _create_task(store, "node_b")
        await store.add_edge("node_a", "node_b")

        spec = PlanRevisionSpec(
            board_id="b_replan",
            rationale="Introduce cyclic dependency",
            task_changes=(),
            add_edges=(("node_b", "node_a"),),
        )
        outcome = await store.revise_plan(spec)
        assert outcome.ok is False
        assert "cycle" in outcome.reason


    async def test_remove_edge_and_task_success(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        t1 = await _create_task(store, "t_del_1")
        t2 = await _create_task(store, "t_del_2")
        await store.add_edge("t_del_1", "t_del_2")

        spec = PlanRevisionSpec(
            board_id="b_replan",
            rationale="Prune redundant branch",
            task_changes=(
                TaskRevisionItem(
                    action="remove",
                    task_id="t_del_2",
                ),
            ),
            remove_edges=(("t_del_1", "t_del_2"),),
        )
        outcome = await store.revise_plan(spec)
        assert outcome.ok is True
        assert "t_del_2" in outcome.removed_task_ids

        # Verify task is archived and edges removed
        t_del_2 = await store.get_task("t_del_2")
        assert t_del_2 is not None
        assert t_del_2.status == TaskStatus.ARCHIVED
        children = await store.list_children("t_del_1")
        assert "t_del_2" not in children


class TestOrchestratorToolReplan:
    async def test_orchestrator_tool_revise_plan_success(
        self,
        store: InMemoryKanbanStore,
        board: KanbanBoard,
    ) -> None:
        await _create_task(store, "step1")
        tools = build_orchestrator_tools(store, None, default_board_id="b_replan")
        replan_tool = next((t for t in tools if t.name == "kanban_revise_plan"), None)
        assert replan_tool is not None

        changes_json = json.dumps(
            [
                {
                    "action": "add",
                    "task_id": "step2",
                    "title": "Step 2",
                    "depends_on": ["step1"],
                },
            ]
        )
        add_edges_json = json.dumps([["step1", "step2"]])

        res = await replan_tool.ainvoke(
            {
                "rationale": "AI dynamic replan based on findings",
                "board_id": "b_replan",
                "changes_json": changes_json,
                "add_edges_json": add_edges_json,
                "remove_edges_json": "[]",
            }
        )
        data = json.loads(res)
        assert data["status"] == "applied"
        assert "step2" in data["added_task_ids"]
