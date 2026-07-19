"""Tests for Kanban dependency DAG: edge management, cycle detection, and promotion."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    KanbanBoard,
    KanbanTask,
    TaskEdge,
    TaskEventKind,
    TaskPriority,
    TaskStatus,
)


@pytest.fixture
def store() -> InMemoryKanbanStore:
    return InMemoryKanbanStore()


@pytest.fixture
async def board(store: InMemoryKanbanStore) -> KanbanBoard:
    b = KanbanBoard(board_id="b1", name="Test Board")
    return await store.save_board(b)


async def _create_task(
    store: InMemoryKanbanStore,
    task_id: str,
    board_id: str = "b1",
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


# ---------------------------------------------------------------------------
# Edge CRUD tests
# ---------------------------------------------------------------------------


class TestEdgeCRUD:
    async def test_add_edge_creates_edge(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "parent")
        await _create_task(store, "child")
        edge = await store.add_edge("parent", "child")
        assert isinstance(edge, TaskEdge)
        assert edge.parent_task_id == "parent"
        assert edge.child_task_id == "child"

    async def test_add_edge_idempotent(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "p1")
        await _create_task(store, "c1")
        e1 = await store.add_edge("p1", "c1")
        e2 = await store.add_edge("p1", "c1")
        assert e1.parent_task_id == e2.parent_task_id
        parents = await store.list_parents("c1")
        assert len(parents) == 1

    async def test_remove_edge(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "p1")
        await _create_task(store, "c1")
        await store.add_edge("p1", "c1")
        assert await store.remove_edge("p1", "c1") is True
        assert await store.list_parents("c1") == []

    async def test_remove_nonexistent_edge(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        assert await store.remove_edge("x", "y") is False

    async def test_list_parents(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "p1")
        await _create_task(store, "p2")
        await _create_task(store, "child")
        await store.add_edge("p1", "child")
        await store.add_edge("p2", "child")
        parents = await store.list_parents("child")
        assert sorted(parents) == ["p1", "p2"]

    async def test_list_children(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "parent")
        await _create_task(store, "c1")
        await _create_task(store, "c2")
        await store.add_edge("parent", "c1")
        await store.add_edge("parent", "c2")
        children = await store.list_children("parent")
        assert sorted(children) == ["c1", "c2"]

    async def test_purge_task_removes_edges(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "p1")
        await _create_task(store, "c1")
        await store.add_edge("p1", "c1")
        await store.delete_task("p1")
        assert await store.list_parents("c1") == []

    async def test_to_dict(self) -> None:
        edge = TaskEdge(parent_task_id="p", child_task_id="c")
        d = edge.to_dict()
        assert d == {"parent_task_id": "p", "child_task_id": "c"}


# ---------------------------------------------------------------------------
# Cycle detection tests
# ---------------------------------------------------------------------------


class TestCycleDetection:
    async def test_self_loop_rejected(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "t1")
        with pytest.raises(ValueError, match="cycle"):
            await store.add_edge("t1", "t1")

    async def test_direct_cycle_rejected(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "a")
        await _create_task(store, "b")
        await store.add_edge("a", "b")
        with pytest.raises(ValueError, match="cycle"):
            await store.add_edge("b", "a")

    async def test_transitive_cycle_rejected(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "a")
        await _create_task(store, "b")
        await _create_task(store, "c")
        await store.add_edge("a", "b")
        await store.add_edge("b", "c")
        with pytest.raises(ValueError, match="cycle"):
            await store.add_edge("c", "a")

    async def test_diamond_dag_allowed(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "a")
        await _create_task(store, "b")
        await _create_task(store, "c")
        await _create_task(store, "d")
        await store.add_edge("a", "b")
        await store.add_edge("a", "c")
        await store.add_edge("b", "d")
        await store.add_edge("c", "d")
        parents = await store.list_parents("d")
        assert sorted(parents) == ["b", "c"]


# ---------------------------------------------------------------------------
# are_dependencies_met tests
# ---------------------------------------------------------------------------


class TestDependenciesMet:
    async def test_no_parents_met(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "t1")
        assert await store.are_dependencies_met("t1") is True

    async def test_all_parents_completed(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "p1", status=TaskStatus.COMPLETED)
        await _create_task(store, "child", status=TaskStatus.BACKLOG)
        await store.add_edge("p1", "child")
        assert await store.are_dependencies_met("child") is True

    async def test_some_parents_not_terminal(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "p1", status=TaskStatus.COMPLETED)
        await _create_task(store, "p2", status=TaskStatus.RUNNING)
        await _create_task(store, "child", status=TaskStatus.BACKLOG)
        await store.add_edge("p1", "child")
        await store.add_edge("p2", "child")
        assert await store.are_dependencies_met("child") is False

    async def test_failed_parent_counts_as_met(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "p1", status=TaskStatus.FAILED)
        await _create_task(store, "child", status=TaskStatus.BACKLOG)
        await store.add_edge("p1", "child")
        assert await store.are_dependencies_met("child") is True

    async def test_archived_parent_counts_as_met(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "p1", status=TaskStatus.ARCHIVED)
        await _create_task(store, "child", status=TaskStatus.BACKLOG)
        await store.add_edge("p1", "child")
        assert await store.are_dependencies_met("child") is True


# ---------------------------------------------------------------------------
# Dispatcher promote tests
# ---------------------------------------------------------------------------


class TestDispatcherPromote:
    async def test_promote_on_success(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        """When parent completes, BACKLOG child should be promotable."""
        parent = await _create_task(store, "parent", status=TaskStatus.COMPLETED)
        child = await _create_task(store, "child", status=TaskStatus.BACKLOG)
        await store.add_edge(parent.task_id, child.task_id)

        assert await store.are_dependencies_met(child.task_id) is True

        child_fresh = await store.get_task(child.task_id)
        assert child_fresh is not None
        assert child_fresh.status == TaskStatus.BACKLOG

        if await store.are_dependencies_met(child.task_id):
            child_fresh.status = TaskStatus.READY
            await store.save_task(child_fresh)
            await store.append_event(
                child.task_id,
                TaskEventKind.PROMOTED,
                payload={"trigger_task_id": parent.task_id},
            )

        promoted = await store.get_task(child.task_id)
        assert promoted is not None
        assert promoted.status == TaskStatus.READY

        events = await store.list_events(child.task_id)
        promoted_events = [e for e in events if e.kind == TaskEventKind.PROMOTED]
        assert len(promoted_events) == 1

    async def test_no_promote_when_deps_unmet(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "p1", status=TaskStatus.COMPLETED)
        await _create_task(store, "p2", status=TaskStatus.RUNNING)
        child = await _create_task(store, "child", status=TaskStatus.BACKLOG)
        await store.add_edge("p1", child.task_id)
        await store.add_edge("p2", child.task_id)

        assert await store.are_dependencies_met(child.task_id) is False

    async def test_multi_child_promotion(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        parent = await _create_task(store, "parent", status=TaskStatus.COMPLETED)
        c1 = await _create_task(store, "c1", status=TaskStatus.BACKLOG)
        c2 = await _create_task(store, "c2", status=TaskStatus.BACKLOG)
        await store.add_edge(parent.task_id, c1.task_id)
        await store.add_edge(parent.task_id, c2.task_id)

        children = await store.list_children(parent.task_id)
        assert len(children) == 2
        for cid in children:
            assert await store.are_dependencies_met(cid) is True


# ---------------------------------------------------------------------------
# TaskEventKind.PROMOTED tests
# ---------------------------------------------------------------------------


class TestEdgeBoundary:
    """Edge cases and boundary conditions."""

    async def test_long_chain_no_cycle(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        """A→B→C→D→E is a valid chain, not a cycle."""
        for tid in ["a", "b", "c", "d", "e"]:
            await _create_task(store, tid)
        await store.add_edge("a", "b")
        await store.add_edge("b", "c")
        await store.add_edge("c", "d")
        await store.add_edge("d", "e")
        assert await store.list_parents("e") == ["d"]
        assert await store.list_children("a") == ["b"]

    async def test_multiple_parents_single_child(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        """Child with 5 parents — all must be terminal for deps_met."""
        for i in range(5):
            await _create_task(store, f"p{i}", status=TaskStatus.READY)
        child = await _create_task(store, "child", status=TaskStatus.BACKLOG)
        for i in range(5):
            await store.add_edge(f"p{i}", child.task_id)

        assert await store.are_dependencies_met(child.task_id) is False

        for i in range(4):
            p = await store.get_task(f"p{i}")
            assert p is not None
            p.status = TaskStatus.COMPLETED
            await store.save_task(p)

        assert await store.are_dependencies_met(child.task_id) is False

        last = await store.get_task("p4")
        assert last is not None
        last.status = TaskStatus.COMPLETED
        await store.save_task(last)
        assert await store.are_dependencies_met(child.task_id) is True

    async def test_delete_board_cascades_edges(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        """Deleting a board should clean up edges of all tasks."""
        p = await _create_task(store, "p1")
        c = await _create_task(store, "c1")
        await store.add_edge(p.task_id, c.task_id)
        await store.delete_board(board.board_id)
        assert store._edges == []

    async def test_child_already_ready_not_in_backlog(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        """are_dependencies_met still returns True even if child is READY (not BACKLOG)."""
        p = await _create_task(store, "p1", status=TaskStatus.COMPLETED)
        c = await _create_task(store, "c1", status=TaskStatus.READY)
        await store.add_edge(p.task_id, c.task_id)
        assert await store.are_dependencies_met(c.task_id) is True

    async def test_remove_then_readd_edge(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "p")
        await _create_task(store, "c")
        await store.add_edge("p", "c")
        await store.remove_edge("p", "c")
        assert await store.list_parents("c") == []
        await store.add_edge("p", "c")
        assert await store.list_parents("c") == ["p"]

    async def test_two_independent_dags(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        """Two independent DAGs should not interfere with each other."""
        for tid in ["a1", "b1", "a2", "b2"]:
            await _create_task(store, tid)
        await store.add_edge("a1", "b1")
        await store.add_edge("a2", "b2")
        assert await store.list_parents("b1") == ["a1"]
        assert await store.list_parents("b2") == ["a2"]
        assert await store.list_children("a1") == ["b1"]

    async def test_no_edges_returns_empty_lists(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "solo")
        assert await store.list_parents("solo") == []
        assert await store.list_children("solo") == []


class TestAgentToolDependencyActions:
    """Test kanban_add_task depends_on via orchestrator tools."""

    def _get_tool(self, tools: list, name: str):
        return next(t for t in tools if t.name == name)

    async def test_add_dependency_demotes_ready_to_backlog(
        self,
        store: InMemoryKanbanStore,
        board: KanbanBoard,
    ) -> None:
        from myrm_agent_harness.toolkits.kanban import create_kanban_tools

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id=board.board_id)
        add_task = self._get_tool(tools, "kanban_add_task")

        await _create_task(store, "parent", status=TaskStatus.READY)
        result = await add_task.ainvoke({
            "title": "Child",
            "depends_on": "parent",
        })
        assert '"added"' in result

        import json
        child_id = json.loads(result)["task"]["task_id"]
        child = await store.get_task(child_id)
        assert child is not None
        assert child.status == TaskStatus.BACKLOG

    async def test_remove_dependency_promotes_backlog_to_ready(
        self,
        store: InMemoryKanbanStore,
        board: KanbanBoard,
    ) -> None:
        p = await _create_task(store, "parent", status=TaskStatus.COMPLETED)
        c = await _create_task(store, "child", status=TaskStatus.BACKLOG)
        await store.add_edge(p.task_id, c.task_id)

        removed = await store.remove_edge(p.task_id, c.task_id)
        assert removed is True
        if await store.are_dependencies_met(c.task_id):
            child = await store.get_task(c.task_id)
            assert child is not None
            child.status = TaskStatus.READY
            await store.save_task(child)

        child = await store.get_task(c.task_id)
        assert child is not None
        assert child.status == TaskStatus.READY

    async def test_add_task_with_depends_on(
        self,
        store: InMemoryKanbanStore,
        board: KanbanBoard,
    ) -> None:
        from myrm_agent_harness.toolkits.kanban import create_kanban_tools

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id=board.board_id)
        add_task = self._get_tool(tools, "kanban_add_task")

        await _create_task(store, "p1")
        await _create_task(store, "p2")

        result = await add_task.ainvoke({
            "title": "Child Task",
            "description": "desc",
            "priority": "normal",
            "depends_on": "p1,p2",
        })
        import json

        data = json.loads(result)
        assert data["status"] == "added"
        assert data["task"]["status"] == "backlog"

        child_id = data["task"]["task_id"]
        parents = await store.list_parents(child_id)
        assert sorted(parents) == ["p1", "p2"]

    async def test_add_task_without_depends_on_is_ready(
        self,
        store: InMemoryKanbanStore,
        board: KanbanBoard,
    ) -> None:
        from myrm_agent_harness.toolkits.kanban import create_kanban_tools

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id=board.board_id)
        add_task = self._get_tool(tools, "kanban_add_task")

        result = await add_task.ainvoke({
            "title": "Solo Task",
            "description": "desc",
        })
        import json

        data = json.loads(result)
        assert data["task"]["status"] == "ready"

    async def test_add_task_invalid_parent_skipped(
        self,
        store: InMemoryKanbanStore,
        board: KanbanBoard,
    ) -> None:
        """If all depends_on parents don't exist, edges are skipped and task falls back to READY."""
        from myrm_agent_harness.toolkits.kanban import create_kanban_tools

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id=board.board_id)
        add_task = self._get_tool(tools, "kanban_add_task")

        result = await add_task.ainvoke({
            "title": "Child",
            "description": "desc",
            "depends_on": "nonexistent",
        })
        import json

        data = json.loads(result)
        assert data["status"] == "added"
        assert data["task"]["status"] == "ready"

    async def test_add_dependency_cycle_returns_error(
        self,
        store: InMemoryKanbanStore,
        board: KanbanBoard,
    ) -> None:
        await _create_task(store, "a")
        await _create_task(store, "b")
        await store.add_edge("a", "b")
        with pytest.raises(ValueError, match="cycle"):
            await store.add_edge("b", "a")


class TestDispatcherFailedPromote:
    """Test that dispatcher promotes children when parent fails (exhausts retries)."""

    async def test_failed_parent_promotes_child(
        self,
        store: InMemoryKanbanStore,
        board: KanbanBoard,
    ) -> None:
        parent = await _create_task(store, "parent", status=TaskStatus.FAILED)
        child = await _create_task(store, "child", status=TaskStatus.BACKLOG)
        await store.add_edge(parent.task_id, child.task_id)

        assert await store.are_dependencies_met(child.task_id) is True

        if await store.are_dependencies_met(child.task_id):
            child.status = TaskStatus.READY
            await store.save_task(child)
            await store.append_event(
                child.task_id,
                TaskEventKind.PROMOTED,
                payload={"trigger_task_id": parent.task_id},
            )

        promoted = await store.get_task(child.task_id)
        assert promoted is not None
        assert promoted.status == TaskStatus.READY

    async def test_blocked_parent_does_not_promote(
        self,
        store: InMemoryKanbanStore,
        board: KanbanBoard,
    ) -> None:
        parent = await _create_task(store, "parent", status=TaskStatus.BLOCKED)
        child = await _create_task(store, "child", status=TaskStatus.BACKLOG)
        await store.add_edge(parent.task_id, child.task_id)
        assert await store.are_dependencies_met(child.task_id) is False


class TestPromotedEvent:
    async def test_promoted_event_kind_exists(self) -> None:
        assert TaskEventKind.PROMOTED == "promoted"

    async def test_promoted_event_in_list(
        self, store: InMemoryKanbanStore, board: KanbanBoard
    ) -> None:
        await _create_task(store, "t1")
        await store.append_event(
            "t1", TaskEventKind.PROMOTED, payload={"reason": "test"}
        )
        events = await store.list_events("t1")
        assert len(events) == 1
        assert events[0].kind == TaskEventKind.PROMOTED
        assert events[0].payload == {"reason": "test"}
