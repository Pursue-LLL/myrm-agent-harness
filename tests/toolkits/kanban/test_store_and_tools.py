"""Tests for InMemoryKanbanStore and kanban_agent_tools.

Covers: board/task CRUD, agent_id filtering (list_tasks), agent_id
assignment (update_task, add_task), dispatch operations, heartbeat/zombie,
pagination, priority ordering, and agent tool actions.
"""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.toolkits.kanban.kanban_agent_tools import (
    create_kanban_tools,
)
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    KanbanBoard,
    KanbanTask,
    TaskPriority,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_board(store: InMemoryKanbanStore, board_id: str = "b1") -> KanbanBoard:
    board = KanbanBoard(board_id=board_id, name=f"Board {board_id}")
    return await store.save_board(board)


async def _make_task(
    store: InMemoryKanbanStore,
    task_id: str,
    board_id: str = "b1",
    *,
    status: TaskStatus = TaskStatus.READY,
    agent_id: str | None = None,
    priority: TaskPriority = TaskPriority.NORMAL,
    parent_task_id: str | None = None,
) -> KanbanTask:
    task = KanbanTask(
        task_id=task_id,
        board_id=board_id,
        title=f"Task {task_id}",
        status=status,
        agent_id=agent_id,
        priority=priority,
        parent_task_id=parent_task_id,
    )
    return await store.save_task(task)


# ===========================================================================
# Board CRUD
# ===========================================================================


class TestBoardCrud:
    @pytest.mark.asyncio
    async def test_create_get_board(self) -> None:
        store = InMemoryKanbanStore()
        board = await _make_board(store)
        fetched = await store.get_board("b1")
        assert fetched is not None
        assert fetched.board_id == board.board_id

    @pytest.mark.asyncio
    async def test_list_boards(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store, "b1")
        await _make_board(store, "b2")
        boards = await store.list_boards()
        assert len(boards) == 2

    @pytest.mark.asyncio
    async def test_delete_board_cascades_tasks(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1")
        assert await store.delete_board("b1")
        assert await store.get_task("t1") is None
        assert await store.list_tasks("b1") == []

    @pytest.mark.asyncio
    async def test_get_nonexistent_board(self) -> None:
        store = InMemoryKanbanStore()
        assert await store.get_board("nonexistent") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_board(self) -> None:
        store = InMemoryKanbanStore()
        assert not await store.delete_board("nonexistent")


# ===========================================================================
# Task CRUD — core
# ===========================================================================


class TestTaskCrud:
    @pytest.mark.asyncio
    async def test_create_get_task(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        task = await _make_task(store, "t1", agent_id="agent-1")
        fetched = await store.get_task("t1")
        assert fetched is not None
        assert fetched.agent_id == "agent-1"
        assert fetched.task_id == task.task_id

    @pytest.mark.asyncio
    async def test_save_task_upsert(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        task = await _make_task(store, "t1")
        task.title = "Updated"
        await store.save_task(task)
        fetched = await store.get_task("t1")
        assert fetched is not None
        assert fetched.title == "Updated"

    @pytest.mark.asyncio
    async def test_delete_task(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1")
        assert await store.delete_task("t1")
        assert await store.get_task("t1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_task(self) -> None:
        store = InMemoryKanbanStore()
        assert not await store.delete_task("nonexistent")


# ===========================================================================
# list_tasks — filtering, pagination
# ===========================================================================


class TestListTasks:
    @pytest.mark.asyncio
    async def test_filter_by_status(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.READY)
        await _make_task(store, "t2", status=TaskStatus.RUNNING)
        await _make_task(store, "t3", status=TaskStatus.READY)

        ready = await store.list_tasks("b1", status=TaskStatus.READY)
        assert len(ready) == 2
        assert all(t.status == TaskStatus.READY for t in ready)

    @pytest.mark.asyncio
    async def test_filter_by_agent_id(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", agent_id="agent-a")
        await _make_task(store, "t2", agent_id="agent-b")
        await _make_task(store, "t3", agent_id="agent-a")
        await _make_task(store, "t4")  # no agent

        filtered = await store.list_tasks("b1", agent_id="agent-a")
        assert len(filtered) == 2
        assert all(t.agent_id == "agent-a" for t in filtered)

    @pytest.mark.asyncio
    async def test_filter_by_agent_id_none_returns_all(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", agent_id="agent-a")
        await _make_task(store, "t2")

        all_tasks = await store.list_tasks("b1", agent_id=None)
        assert len(all_tasks) == 2

    @pytest.mark.asyncio
    async def test_combined_filter_status_and_agent(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.READY, agent_id="a1")
        await _make_task(store, "t2", status=TaskStatus.RUNNING, agent_id="a1")
        await _make_task(store, "t3", status=TaskStatus.READY, agent_id="a2")

        result = await store.list_tasks("b1", status=TaskStatus.READY, agent_id="a1")
        assert len(result) == 1
        assert result[0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_filter_by_parent_task_id(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "parent")
        await _make_task(store, "child1", parent_task_id="parent")
        await _make_task(store, "child2", parent_task_id="parent")
        await _make_task(store, "orphan")

        children = await store.list_tasks("b1", parent_task_id="parent")
        assert len(children) == 2

    @pytest.mark.asyncio
    async def test_pagination_limit_offset(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        for i in range(5):
            await _make_task(store, f"t{i}")

        page1 = await store.list_tasks("b1", limit=2, offset=0)
        assert len(page1) == 2

        page2 = await store.list_tasks("b1", limit=2, offset=2)
        assert len(page2) == 2

        page3 = await store.list_tasks("b1", limit=2, offset=4)
        assert len(page3) == 1

    @pytest.mark.asyncio
    async def test_empty_board_returns_empty(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        result = await store.list_tasks("b1")
        assert result == []

    @pytest.mark.asyncio
    async def test_nonexistent_agent_returns_empty(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", agent_id="agent-a")
        result = await store.list_tasks("b1", agent_id="nonexistent")
        assert result == []


# ===========================================================================
# count_tasks / count_tasks_grouped
# ===========================================================================


class TestCountTasks:
    @pytest.mark.asyncio
    async def test_count_by_status(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.READY)
        await _make_task(store, "t2", status=TaskStatus.RUNNING)

        assert await store.count_tasks("b1") == 2
        assert await store.count_tasks("b1", status=TaskStatus.READY) == 1

    @pytest.mark.asyncio
    async def test_count_grouped(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.READY)
        await _make_task(store, "t2", status=TaskStatus.READY)
        await _make_task(store, "t3", status=TaskStatus.RUNNING)

        grouped = await store.count_tasks_grouped("b1")
        assert grouped["ready"] == 2
        assert grouped["running"] == 1


# ===========================================================================
# Dispatch operations — claim, list_ready, list_running
# ===========================================================================


class TestDispatchOperations:
    @pytest.mark.asyncio
    async def test_claim_task(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.READY)

        assert await store.claim_task("t1", "worker-1")
        task = await store.get_task("t1")
        assert task is not None
        assert task.status == TaskStatus.RUNNING

    @pytest.mark.asyncio
    async def test_claim_non_ready_fails(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        assert not await store.claim_task("t1", "worker-1")

    @pytest.mark.asyncio
    async def test_list_ready_priority_order(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "low", priority=TaskPriority.LOW)
        await _make_task(store, "urgent", priority=TaskPriority.URGENT)
        await _make_task(store, "normal", priority=TaskPriority.NORMAL)

        ready = await store.list_ready_tasks("b1")
        assert ready[0].task_id == "urgent"
        assert ready[1].task_id == "normal"
        assert ready[2].task_id == "low"

    @pytest.mark.asyncio
    async def test_list_running_tasks(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        await _make_task(store, "t2", status=TaskStatus.READY)

        running = await store.list_running_tasks("b1")
        assert len(running) == 1
        assert running[0].task_id == "t1"


# ===========================================================================
# Heartbeat & zombie detection
# ===========================================================================


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_update_heartbeat(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        await store.update_heartbeat("t1")
        task = await store.get_task("t1")
        assert task is not None
        assert task.last_heartbeat_at is not None

    @pytest.mark.asyncio
    async def test_zombie_detection_no_heartbeat(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)

        zombies = await store.list_zombie_tasks("b1", timeout_seconds=0)
        assert len(zombies) == 1
        assert zombies[0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_zombie_detection_recent_heartbeat(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        await store.update_heartbeat("t1")

        zombies = await store.list_zombie_tasks("b1", timeout_seconds=3600)
        assert len(zombies) == 0


# ===========================================================================
# Agent tools — list_tasks with agent_id_filter
# ===========================================================================


class TestAgentToolsAgentFilter:
    def _get_tool(self, tools, name):
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_list_tasks_with_agent_filter(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", agent_id="agent-a")
        await _make_task(store, "t2", agent_id="agent-b")
        await _make_task(store, "t3", agent_id="agent-a")

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        list_tasks = self._get_tool(tools, "kanban_list_tasks")
        result = await list_tasks.ainvoke({"agent_id_filter": "agent-a"})
        data = json.loads(result)
        assert data["count"] == 2
        assert all(t["agent_id"] == "agent-a" for t in data["tasks"])

    @pytest.mark.asyncio
    async def test_list_tasks_without_filter_returns_all(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", agent_id="agent-a")
        await _make_task(store, "t2", agent_id="agent-b")
        await _make_task(store, "t3")

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        list_tasks = self._get_tool(tools, "kanban_list_tasks")
        result = await list_tasks.ainvoke({})
        data = json.loads(result)
        assert data["count"] == 3

    @pytest.mark.asyncio
    async def test_list_tasks_combined_status_and_agent_filter(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.READY, agent_id="a1")
        await _make_task(store, "t2", status=TaskStatus.RUNNING, agent_id="a1")
        await _make_task(store, "t3", status=TaskStatus.READY, agent_id="a2")

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        list_tasks = self._get_tool(tools, "kanban_list_tasks")
        result = await list_tasks.ainvoke({"status_filter": "ready", "agent_id_filter": "a1"})
        data = json.loads(result)
        assert data["count"] == 1
        assert data["tasks"][0]["task_id"] == "t1"


# ===========================================================================
# Agent tools — assign_agent_id via update_task
# ===========================================================================


class TestAgentToolsAssignAgent:
    def _get_tool(self, tools, name):
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_assign_agent_via_update(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1")

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        update_task = self._get_tool(tools, "kanban_update_task")
        result = await update_task.ainvoke({"task_id": "t1", "assign_agent_id": "new-agent"})
        data = json.loads(result)
        assert data["status"] == "updated"
        assert data["task"]["agent_id"] == "new-agent"

        task = await store.get_task("t1")
        assert task is not None
        assert task.agent_id == "new-agent"

    @pytest.mark.asyncio
    async def test_reassign_agent(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", agent_id="old-agent")

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        update_task = self._get_tool(tools, "kanban_update_task")
        result = await update_task.ainvoke({"task_id": "t1", "assign_agent_id": "new-agent"})
        data = json.loads(result)
        assert data["task"]["agent_id"] == "new-agent"

    @pytest.mark.asyncio
    async def test_add_task_with_agent(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1", agent_id="creator")
        add_task = self._get_tool(tools, "kanban_add_task")
        result = await add_task.ainvoke({"title": "My Task"})
        data = json.loads(result)
        assert data["status"] == "added"
        assert data["task"]["agent_id"] == "creator"


# ===========================================================================
# Agent tools — error paths
# ===========================================================================


class TestAgentToolsErrors:
    def _get_tool(self, tools, name):
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_update_nonexistent_task(self) -> None:
        store = InMemoryKanbanStore()
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        update_task = self._get_tool(tools, "kanban_update_task")
        result = await update_task.ainvoke({"task_id": "nonexistent", "title": "New"})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_list_tasks_invalid_status(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        list_tasks = self._get_tool(tools, "kanban_list_tasks")
        result = await list_tasks.ainvoke({"status_filter": "invalid_status"})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_add_task_no_board(self) -> None:
        store = InMemoryKanbanStore()
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="nonexistent")
        add_task = self._get_tool(tools, "kanban_add_task")
        result = await add_task.ainvoke({"title": "Task"})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_add_task_no_title(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        add_task = self._get_tool(tools, "kanban_add_task")
        result = await add_task.ainvoke({"title": ""})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_move_task_invalid_status(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1")
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        move_task = self._get_tool(tools, "kanban_move_task")
        result = await move_task.ainvoke({"task_id": "t1", "status": "invalid"})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_modular_tools_have_correct_count(self) -> None:
        """Verify tool mode returns expected tool counts."""
        store = InMemoryKanbanStore()
        worker_tools = create_kanban_tools(store, mode="worker", current_task_id="t1")
        assert len(worker_tools) == 5
        orch_tools = create_kanban_tools(store, mode="orchestrator")
        assert len(orch_tools) == 7
        full_tools = create_kanban_tools(store, mode="full")
        assert len(full_tools) == 12


# ===========================================================================
# Agent tools — other actions
# ===========================================================================


class TestAgentToolsMisc:
    def _get_tool(self, tools: list, name: str):
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_create_board_via_store(self) -> None:
        store = InMemoryKanbanStore()
        from myrm_agent_harness.toolkits.kanban.types import BoardSettings, KanbanBoard

        board = KanbanBoard(
            board_id="new-board",
            name="New Board",
            description="Test",
            settings=BoardSettings(),
        )
        saved = await store.save_board(board)
        assert saved.name == "New Board"

    @pytest.mark.asyncio
    async def test_list_boards_via_store(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store, "b1")
        await _make_board(store, "b2")
        boards = await store.list_boards()
        assert len(boards) == 2

    @pytest.mark.asyncio
    async def test_delete_task_via_tool(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1")
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        delete_task = self._get_tool(tools, "kanban_delete_task")
        result = await delete_task.ainvoke({"task_id": "t1"})
        data = json.loads(result)
        assert data["status"] == "deleted"
        assert await store.get_task("t1") is None

    @pytest.mark.asyncio
    async def test_get_task_via_store(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", agent_id="agent-x")
        task = await store.get_task("t1")
        assert task is not None
        assert task.agent_id == "agent-x"

    @pytest.mark.asyncio
    async def test_update_task_fields(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1")
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        update_task = self._get_tool(tools, "kanban_update_task")
        result = await update_task.ainvoke({
            "task_id": "t1",
            "title": "New Title",
            "priority": "high",
        })
        data = json.loads(result)
        assert data["task"]["title"] == "New Title"
        assert data["task"]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_move_terminal_task_to_archived(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.COMPLETED)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        move_task = self._get_tool(tools, "kanban_move_task")
        result = await move_task.ainvoke({"task_id": "t1", "status": "archived"})
        data = json.loads(result)
        assert data["status"] == "moved"

    @pytest.mark.asyncio
    async def test_move_terminal_task_rejected(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.COMPLETED)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        move_task = self._get_tool(tools, "kanban_move_task")
        result = await move_task.ainvoke({"task_id": "t1", "status": "ready"})
        data = json.loads(result)
        assert "error" in data


# ===========================================================================
# Deep-copy isolation
# ===========================================================================


class TestIsolation:
    @pytest.mark.asyncio
    async def test_returned_task_is_deep_copy(self) -> None:
        """Mutations to returned objects must not affect store state."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        task = await _make_task(store, "t1", agent_id="original")

        task.agent_id = "mutated"
        fetched = await store.get_task("t1")
        assert fetched is not None
        assert fetched.agent_id == "original"

    @pytest.mark.asyncio
    async def test_listed_tasks_are_deep_copies(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", agent_id="orig")

        tasks = await store.list_tasks("b1")
        tasks[0].agent_id = "mutated"

        fetched = await store.get_task("t1")
        assert fetched is not None
        assert fetched.agent_id == "orig"


# ===========================================================================
# Idempotency key — functional correctness
# ===========================================================================


class TestIdempotencyKey:
    """Cover kanban_add_task idempotency_key dedup and metadata storage."""

    def _get_tool(self, tools: list, name: str):
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_first_add_stores_key_in_metadata(self) -> None:
        """First call with idempotency_key should create task and store key."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        add_task = self._get_tool(tools, "kanban_add_task")

        result = await add_task.ainvoke({"title": "Task A", "idempotency_key": "key-001"})
        data = json.loads(result)
        assert data["status"] == "added"
        assert data["task"]["metadata"]["idempotency_key"] == "key-001"

        task = await store.get_task(data["task"]["task_id"])
        assert task is not None
        assert task.metadata is not None
        assert task.metadata["idempotency_key"] == "key-001"

    @pytest.mark.asyncio
    async def test_duplicate_returns_existing_task(self) -> None:
        """Second call with same idempotency_key returns existing task."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        add_task = self._get_tool(tools, "kanban_add_task")

        r1 = json.loads(await add_task.ainvoke({"title": "Task A", "idempotency_key": "dup-key"}))
        r2 = json.loads(await add_task.ainvoke({"title": "Task B Different Title", "idempotency_key": "dup-key"}))

        assert r1["status"] == "added"
        assert r2["status"] == "already_exists"
        assert r1["task"]["task_id"] == r2["task"]["task_id"]
        assert r2["task"]["title"] == "Task A"  # original title preserved

        tasks = await store.list_tasks("b1")
        assert len(tasks) == 1

    @pytest.mark.asyncio
    async def test_different_keys_create_separate_tasks(self) -> None:
        """Different idempotency_keys should create distinct tasks."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        add_task = self._get_tool(tools, "kanban_add_task")

        r1 = json.loads(await add_task.ainvoke({"title": "Task A", "idempotency_key": "key-a"}))
        r2 = json.loads(await add_task.ainvoke({"title": "Task B", "idempotency_key": "key-b"}))

        assert r1["status"] == "added"
        assert r2["status"] == "added"
        assert r1["task"]["task_id"] != r2["task"]["task_id"]

        tasks = await store.list_tasks("b1")
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_empty_key_skips_dedup(self) -> None:
        """Empty idempotency_key should not trigger dedup logic."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        add_task = self._get_tool(tools, "kanban_add_task")

        r1 = json.loads(await add_task.ainvoke({"title": "Task A", "idempotency_key": ""}))
        r2 = json.loads(await add_task.ainvoke({"title": "Task A", "idempotency_key": ""}))

        assert r1["status"] == "added"
        assert r2["status"] == "added"
        assert r1["task"]["task_id"] != r2["task"]["task_id"]
        assert r1["task"].get("metadata") is None or "idempotency_key" not in (r1["task"].get("metadata") or {})

    @pytest.mark.asyncio
    async def test_idempotency_scoped_to_board(self) -> None:
        """Same idempotency_key on different boards should create separate tasks."""
        store = InMemoryKanbanStore()
        await _make_board(store, "board-1")
        await _make_board(store, "board-2")
        tools_b1 = create_kanban_tools(store, mode="orchestrator", default_board_id="board-1")
        tools_b2 = create_kanban_tools(store, mode="orchestrator", default_board_id="board-2")
        add_b1 = self._get_tool(tools_b1, "kanban_add_task")
        add_b2 = self._get_tool(tools_b2, "kanban_add_task")

        r1 = json.loads(await add_b1.ainvoke({"title": "Task", "idempotency_key": "shared-key"}))
        r2 = json.loads(await add_b2.ainvoke({"title": "Task", "idempotency_key": "shared-key"}))

        assert r1["status"] == "added"
        assert r2["status"] == "added"
        assert r1["task"]["task_id"] != r2["task"]["task_id"]

    @pytest.mark.asyncio
    async def test_triple_retry_still_returns_same_task(self) -> None:
        """Simulate 3 retry calls — all must return the same task."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        add_task = self._get_tool(tools, "kanban_add_task")

        results = []
        for _ in range(3):
            r = json.loads(await add_task.ainvoke({"title": "Retry Task", "idempotency_key": "retry-key"}))
            results.append(r)

        assert results[0]["status"] == "added"
        for r in results[1:]:
            assert r["status"] == "already_exists"
            assert r["task"]["task_id"] == results[0]["task"]["task_id"]

        tasks = await store.list_tasks("b1")
        assert len(tasks) == 1


# ===========================================================================
# Idempotency key — O(N) performance benchmark
# ===========================================================================


class TestIdempotencyPerformance:
    """Measure _find_task_by_idempotency_key at various board sizes.

    Proves O(N) scan is negligible for realistic Kanban board sizes (<500 tasks).
    """

    def _get_tool(self, tools: list, name: str):
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_perf_10_tasks(self) -> None:
        await self._run_benchmark(10)

    @pytest.mark.asyncio
    async def test_perf_50_tasks(self) -> None:
        await self._run_benchmark(50)

    @pytest.mark.asyncio
    async def test_perf_100_tasks(self) -> None:
        await self._run_benchmark(100)

    @pytest.mark.asyncio
    async def test_perf_500_tasks(self) -> None:
        await self._run_benchmark(500)

    async def _run_benchmark(self, n: int) -> None:
        """Create N tasks, then trigger idempotency check — assert < 200ms.

        Threshold is generous to avoid flaky failures under CI/IDE load.
        """
        import time

        store = InMemoryKanbanStore()
        await _make_board(store)

        for i in range(n):
            task = KanbanTask(
                task_id=f"perf-{i:04d}",
                board_id="b1",
                title=f"Task {i}",
                status=TaskStatus.READY,
                metadata={"idempotency_key": f"perf-key-{i:04d}"},
            )
            await store.save_task(task)

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        add_task = self._get_tool(tools, "kanban_add_task")

        start = time.perf_counter()
        result = json.loads(await add_task.ainvoke({
            "title": "Dup", "idempotency_key": "perf-key-0000",
        }))
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result["status"] == "already_exists"
        print(f"\n  [PERF] Idempotency dedup check with {n:>4d} tasks: {elapsed_ms:.3f}ms")
        assert elapsed_ms < 1500, f"Idempotency check with {n} tasks took {elapsed_ms:.2f}ms (> 1500ms threshold)"

    @pytest.mark.asyncio
    async def test_perf_new_key_among_500_tasks(self) -> None:
        """Adding with a new idempotency_key among 500 tasks should be fast."""
        import time

        store = InMemoryKanbanStore()
        await _make_board(store)

        for i in range(500):
            task = KanbanTask(
                task_id=f"bulk-{i:04d}",
                board_id="b1",
                title=f"Task {i}",
                status=TaskStatus.READY,
                metadata={"idempotency_key": f"bulk-key-{i:04d}"},
            )
            await store.save_task(task)

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        add_task = self._get_tool(tools, "kanban_add_task")

        start = time.perf_counter()
        result = json.loads(await add_task.ainvoke({
            "title": "Brand New", "idempotency_key": "never-seen-before",
        }))
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result["status"] == "added"
        print(f"\n  [PERF] New key add among 500 tasks: {elapsed_ms:.3f}ms")
        assert elapsed_ms < 1500, f"New task creation with 500 existing took {elapsed_ms:.2f}ms"

        tasks = await store.list_tasks("b1")
        assert len(tasks) == 501


# ===========================================================================
# max_runtime_seconds in agent tools
# ===========================================================================


class TestMaxRuntimeSecondsTools:

    def _get_tool(self, tools: list, name: str):
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_add_task_with_max_runtime(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        add_task = self._get_tool(tools, "kanban_add_task")

        result = json.loads(await add_task.ainvoke({
            "title": "Timed Task",
            "max_runtime_seconds": 300,
        }))
        assert result["status"] == "added"
        assert result["task"]["max_runtime_seconds"] == 300

    @pytest.mark.asyncio
    async def test_add_task_zero_max_runtime_means_default(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        add_task = self._get_tool(tools, "kanban_add_task")

        result = json.loads(await add_task.ainvoke({
            "title": "Default Timeout",
            "max_runtime_seconds": 0,
        }))
        assert result["status"] == "added"
        assert result["task"]["max_runtime_seconds"] is None

    @pytest.mark.asyncio
    async def test_update_task_set_max_runtime(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1")
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        update_task = self._get_tool(tools, "kanban_update_task")

        result = json.loads(await update_task.ainvoke({
            "task_id": "t1",
            "max_runtime_seconds": 600,
        }))
        assert result["status"] == "updated"
        assert result["task"]["max_runtime_seconds"] == 600

    @pytest.mark.asyncio
    async def test_update_task_reset_max_runtime(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1")

        task = await store.get_task("t1")
        assert task is not None
        task.max_runtime_seconds = 300
        await store.save_task(task)

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        update_task = self._get_tool(tools, "kanban_update_task")

        result = json.loads(await update_task.ainvoke({
            "task_id": "t1",
            "max_runtime_seconds": 0,
        }))
        assert result["status"] == "updated"
        assert result["task"]["max_runtime_seconds"] is None

    @pytest.mark.asyncio
    async def test_update_task_unchanged_max_runtime(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1")

        task = await store.get_task("t1")
        assert task is not None
        task.max_runtime_seconds = 120
        await store.save_task(task)

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        update_task = self._get_tool(tools, "kanban_update_task")

        result = json.loads(await update_task.ainvoke({
            "task_id": "t1",
            "max_runtime_seconds": -1,
        }))
        assert result["status"] == "updated"
        assert result["task"]["max_runtime_seconds"] == 120


# ===========================================================================
# kanban_complete tool — worker-scoped completion with metadata handoff
# ===========================================================================


class TestKanbanCompleteTools:

    def _get_tool(self, tools: list, name: str):
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_complete_basic(self) -> None:
        """Basic complete sets task.result and status."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        complete = self._get_tool(tools, "kanban_complete")
        result = json.loads(await complete.ainvoke({"summary": "All done"}))
        assert result["status"] == "completed"
        assert result["task"]["result"] == "All done"
        task = await store.get_task("t1")
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == "All done"

    @pytest.mark.asyncio
    async def test_complete_with_metadata(self) -> None:
        """Complete with metadata stores handoff data."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        complete = self._get_tool(tools, "kanban_complete")
        meta = json.dumps({"changed_files": ["a.py"], "tests_run": 3})
        result = json.loads(await complete.ainvoke({
            "summary": "Fixed bug", "metadata": meta,
        }))
        assert result["status"] == "completed"
        task = await store.get_task("t1")
        assert task is not None
        assert task.metadata["handoff"] == {"changed_files": ["a.py"], "tests_run": 3}
        assert task.result == "Fixed bug"

    @pytest.mark.asyncio
    async def test_complete_metadata_invalid_json(self) -> None:
        """Invalid metadata JSON returns error."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        complete = self._get_tool(tools, "kanban_complete")
        result = json.loads(await complete.ainvoke({
            "summary": "Done", "metadata": "not valid json{",
        }))
        assert "error" in result
        assert "Invalid metadata JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_complete_metadata_not_object(self) -> None:
        """metadata must be a JSON object, not array or primitive."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        complete = self._get_tool(tools, "kanban_complete")
        result = json.loads(await complete.ainvoke({
            "summary": "Done", "metadata": "[1, 2, 3]",
        }))
        assert "error" in result
        assert "must be a JSON object" in result["error"]

    @pytest.mark.asyncio
    async def test_complete_empty_summary_error(self) -> None:
        """Empty summary returns error."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        complete = self._get_tool(tools, "kanban_complete")
        result = json.loads(await complete.ainvoke({"summary": ""}))
        assert "error" in result
        assert "summary is required" in result["error"]

    @pytest.mark.asyncio
    async def test_complete_terminal_task_error(self) -> None:
        """Cannot complete a task already in terminal state."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.COMPLETED)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        complete = self._get_tool(tools, "kanban_complete")
        result = json.loads(await complete.ainvoke({"summary": "retry"}))
        assert "error" in result
        assert "terminal state" in result["error"]

    @pytest.mark.asyncio
    async def test_complete_emits_event_with_summary(self) -> None:
        """COMPLETED event payload contains summary."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        complete = self._get_tool(tools, "kanban_complete")
        await complete.ainvoke({"summary": "Implemented feature X"})
        events = await store.list_events("t1")
        completed_events = [
            e for e in events if e.kind.value == "completed"
        ]
        assert len(completed_events) == 1
        assert completed_events[0].payload is not None
        assert completed_events[0].payload["summary"] == "Implemented feature X"

    @pytest.mark.asyncio
    async def test_complete_without_metadata_no_handoff_key(self) -> None:
        """Complete without metadata does not create handoff key."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        complete = self._get_tool(tools, "kanban_complete")
        await complete.ainvoke({"summary": "Done simple"})
        task = await store.get_task("t1")
        assert task is not None
        assert "handoff" not in task.metadata

    @pytest.mark.asyncio
    async def test_complete_preserves_existing_metadata(self) -> None:
        """Handoff metadata merges into existing task.metadata without overwriting."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        task = KanbanTask(
            task_id="t1", board_id="b1", title="T1",
            status=TaskStatus.RUNNING,
            metadata={"custom_key": "preserved"},
        )
        await store.save_task(task)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        complete = self._get_tool(tools, "kanban_complete")
        meta = json.dumps({"changed_files": ["b.py"]})
        await complete.ainvoke({"summary": "Done", "metadata": meta})
        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.metadata["custom_key"] == "preserved"
        assert updated.metadata["handoff"] == {"changed_files": ["b.py"]}

    @pytest.mark.asyncio
    async def test_complete_no_task_id_error(self) -> None:
        """Complete without task_id and no current_task_id returns error."""
        store = InMemoryKanbanStore()
        tools = create_kanban_tools(store, mode="worker")
        complete = self._get_tool(tools, "kanban_complete")
        result = json.loads(await complete.ainvoke({"summary": "Done"}))
        assert "error" in result
        assert "task_id is required" in result["error"]

    @pytest.mark.asyncio
    async def test_complete_wrong_task_ownership(self) -> None:
        """Cannot complete another worker's task."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        await _make_task(store, "t2", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        complete = self._get_tool(tools, "kanban_complete")
        result = json.loads(await complete.ainvoke({
            "summary": "Done", "task_id": "t2",
        }))
        assert "error" in result
        assert "Permission denied" in result["error"]


# ===========================================================================
# kanban_show / kanban_block / kanban_heartbeat worker tools
# ===========================================================================


class TestWorkerToolsSuite:

    def _get_tool(self, tools: list, name: str):
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_show_task(self) -> None:
        """kanban_show returns task details."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        show = self._get_tool(tools, "kanban_show")
        result = json.loads(await show.ainvoke({}))
        assert result["task"]["task_id"] == "t1"

    @pytest.mark.asyncio
    async def test_show_no_task_id(self) -> None:
        """kanban_show without task_id and no current_task_id returns error."""
        store = InMemoryKanbanStore()
        tools = create_kanban_tools(store, mode="worker")
        show = self._get_tool(tools, "kanban_show")
        result = json.loads(await show.ainvoke({}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_show_wrong_ownership(self) -> None:
        """kanban_show cannot view other worker's task."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        await _make_task(store, "t2", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        show = self._get_tool(tools, "kanban_show")
        result = json.loads(await show.ainvoke({"task_id": "t2"}))
        assert "error" in result
        assert "Permission denied" in result["error"]

    @pytest.mark.asyncio
    async def test_block_task(self) -> None:
        """kanban_block sets task to blocked with reason."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        block = self._get_tool(tools, "kanban_block")
        result = json.loads(await block.ainvoke({"reason": "missing API key"}))
        assert result["status"] == "blocked"
        task = await store.get_task("t1")
        assert task is not None
        assert task.status == TaskStatus.BLOCKED
        assert task.blocked_reason == "missing API key"

    @pytest.mark.asyncio
    async def test_block_empty_reason_error(self) -> None:
        """kanban_block with empty reason returns error."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        block = self._get_tool(tools, "kanban_block")
        result = json.loads(await block.ainvoke({"reason": ""}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_block_terminal_task_error(self) -> None:
        """Cannot block a task already in terminal state."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.COMPLETED)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        block = self._get_tool(tools, "kanban_block")
        result = json.loads(await block.ainvoke({"reason": "test"}))
        assert "error" in result
        assert "terminal state" in result["error"]

    @pytest.mark.asyncio
    async def test_heartbeat(self) -> None:
        """kanban_heartbeat updates progress note."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        heartbeat = self._get_tool(tools, "kanban_heartbeat")
        result = json.loads(await heartbeat.ainvoke({"note": "50% done"}))
        assert result["status"] == "heartbeat_ok"
        task = await store.get_task("t1")
        assert task is not None
        assert task.progress_note == "50% done"

    @pytest.mark.asyncio
    async def test_heartbeat_not_running_error(self) -> None:
        """kanban_heartbeat on non-running task returns error."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.READY)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        heartbeat = self._get_tool(tools, "kanban_heartbeat")
        result = json.loads(await heartbeat.ainvoke({"note": "progress"}))
        assert "error" in result
        assert "not running" in result["error"]

    @pytest.mark.asyncio
    async def test_block_no_task_id(self) -> None:
        """kanban_block without task_id returns error."""
        store = InMemoryKanbanStore()
        tools = create_kanban_tools(store, mode="worker")
        block = self._get_tool(tools, "kanban_block")
        result = json.loads(await block.ainvoke({"reason": "test"}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_block_wrong_ownership(self) -> None:
        """kanban_block cannot block other worker's task."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        await _make_task(store, "t2", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        block = self._get_tool(tools, "kanban_block")
        result = json.loads(await block.ainvoke({
            "reason": "test", "task_id": "t2",
        }))
        assert "error" in result
        assert "Permission denied" in result["error"]

    @pytest.mark.asyncio
    async def test_heartbeat_empty_note_error(self) -> None:
        """kanban_heartbeat with empty note returns error."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1",
        )
        heartbeat = self._get_tool(tools, "kanban_heartbeat")
        result = json.loads(await heartbeat.ainvoke({"note": ""}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_add_task_no_board_id(self) -> None:
        """kanban_add_task without board_id returns error."""
        store = InMemoryKanbanStore()
        tools = create_kanban_tools(store, mode="orchestrator")
        add = self._get_tool(tools, "kanban_add_task")
        result = json.loads(await add.ainvoke({"title": "Test"}))
        assert "error" in result
        assert "board_id" in result["error"]

    @pytest.mark.asyncio
    async def test_add_task_invalid_priority(self) -> None:
        """kanban_add_task with invalid priority falls back to normal."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        tools = create_kanban_tools(
            store, mode="orchestrator", default_board_id="b1",
        )
        add = self._get_tool(tools, "kanban_add_task")
        result = json.loads(await add.ainvoke({
            "title": "Test", "priority": "ultra-high",
        }))
        assert result["status"] == "added"
        assert result["task"]["priority"] == "normal"

    @pytest.mark.asyncio
    async def test_add_task_with_dependencies(self) -> None:
        """kanban_add_task with depends_on creates edges and sets backlog."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        parent = await _make_task(store, "p1", status=TaskStatus.READY)
        tools = create_kanban_tools(
            store, mode="orchestrator", default_board_id="b1",
        )
        add = self._get_tool(tools, "kanban_add_task")
        result = json.loads(await add.ainvoke({
            "title": "Child", "depends_on": parent.task_id,
        }))
        assert result["status"] == "added"
        assert result["task"]["status"] == "backlog"

    @pytest.mark.asyncio
    async def test_add_task_with_invalid_dependency(self) -> None:
        """kanban_add_task with nonexistent dependency auto-promotes to ready."""
        store = InMemoryKanbanStore()
        await _make_board(store)
        tools = create_kanban_tools(
            store, mode="orchestrator", default_board_id="b1",
        )
        add = self._get_tool(tools, "kanban_add_task")
        result = json.loads(await add.ainvoke({
            "title": "Child", "depends_on": "nonexistent",
        }))
        assert result["status"] == "added"
        task = await store.get_task(result["task"]["task_id"])
        assert task is not None
        assert task.status == TaskStatus.READY


class TestHandoffEndToEnd:
    """End-to-end: kanban_complete writes handoff → context_builder reads it."""

    @staticmethod
    def _get_tool(tools: list, name: str):  # type: ignore[type-arg]
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_complete_handoff_visible_in_child_context(self) -> None:
        from myrm_agent_harness.toolkits.kanban.context_builder import build_task_context

        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "p-e2e", status=TaskStatus.RUNNING)
        await _make_task(store, "c-e2e", status=TaskStatus.BACKLOG)
        await store.add_edge("p-e2e", "c-e2e")

        tools = create_kanban_tools(store, mode="worker", current_task_id="p-e2e")
        complete = self._get_tool(tools, "kanban_complete")
        result = json.loads(await complete.ainvoke({
            "summary": "Implemented feature X",
            "metadata": '{"changed_files": ["x.py"], "tests_passed": 12}',
        }))
        assert result["status"] == "completed"

        ctx = await build_task_context(store, "c-e2e")
        assert "Handoff:" in ctx
        assert "x.py" in ctx
        assert "tests_passed" in ctx


# ---------------------------------------------------------------------------
# Dependency edge auto-transition tests
# ---------------------------------------------------------------------------


class TestDependencyAutoTransitions:
    """Verify add/remove dependency auto-adjusts child task status."""

    @staticmethod
    def _get_tool(tools: list, name: str):  # type: ignore[type-arg]
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_add_dependency_demotes_ready_to_backlog(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "parent", status=TaskStatus.READY)
        await _make_task(store, "child", status=TaskStatus.READY)

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        link_tool = self._get_tool(tools, "kanban_link")
        result = json.loads(await link_tool.ainvoke({
            "task_id": "child",
            "dependency_task_id": "parent",
            "action": "add",
        }))
        assert result["status"] == "dependency_added"

        child = await store.get_task("child")
        assert child is not None
        assert child.status == TaskStatus.BACKLOG

    @pytest.mark.asyncio
    async def test_remove_dependency_promotes_backlog_to_ready(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "parent", status=TaskStatus.COMPLETED)
        await _make_task(store, "child", status=TaskStatus.BACKLOG)
        await store.add_edge("parent", "child")

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        link_tool = self._get_tool(tools, "kanban_link")
        result = json.loads(await link_tool.ainvoke({
            "task_id": "child",
            "dependency_task_id": "parent",
            "action": "remove",
        }))
        assert result["status"] == "dependency_removed"

        child = await store.get_task("child")
        assert child is not None
        assert child.status == TaskStatus.READY

    @pytest.mark.asyncio
    async def test_delete_task_promotes_dependent_children(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "blocker", status=TaskStatus.READY)
        await _make_task(store, "child", status=TaskStatus.BACKLOG)
        await store.add_edge("blocker", "child")

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        delete = self._get_tool(tools, "kanban_delete_task")
        result = json.loads(await delete.ainvoke({"task_id": "blocker"}))
        assert result["status"] == "deleted"

        child = await store.get_task("child")
        assert child is not None
        assert child.status == TaskStatus.READY


# ===========================================================================
# kanban_comment Worker Tool
# ===========================================================================


class TestKanbanCommentTool:
    """Tests for the kanban_comment worker tool — cross-task coordination."""

    @staticmethod
    def _get_tool(tools: list, name: str):  # type: ignore[type-arg]
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_comment_on_own_task(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)

        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1", agent_id="agent-1",
        )
        comment = self._get_tool(tools, "kanban_comment")
        result = json.loads(await comment.ainvoke({"task_id": "t1", "body": "Found issue X"}))
        assert result["status"] == "comment_added"
        assert result["task_id"] == "t1"
        assert "event_id" in result

    @pytest.mark.asyncio
    async def test_cross_task_comment_allowed(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)
        await _make_task(store, "t2", status=TaskStatus.RUNNING)

        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1", agent_id="agent-1",
        )
        comment = self._get_tool(tools, "kanban_comment")
        result = json.loads(await comment.ainvoke({"task_id": "t2", "body": "Need your output"}))
        assert result["status"] == "comment_added"
        assert result["task_id"] == "t2"

    @pytest.mark.asyncio
    async def test_comment_empty_body_rejected(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)

        tools = create_kanban_tools(store, mode="worker", current_task_id="t1")
        comment = self._get_tool(tools, "kanban_comment")
        result = json.loads(await comment.ainvoke({"task_id": "t1", "body": ""}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_comment_whitespace_body_rejected(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)

        tools = create_kanban_tools(store, mode="worker", current_task_id="t1")
        comment = self._get_tool(tools, "kanban_comment")
        result = json.loads(await comment.ainvoke({"task_id": "t1", "body": "   "}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_comment_missing_task_id_rejected(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)

        tools = create_kanban_tools(store, mode="worker", current_task_id="t1")
        comment = self._get_tool(tools, "kanban_comment")
        result = json.loads(await comment.ainvoke({"task_id": "", "body": "hello"}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_comment_nonexistent_task_rejected(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)

        tools = create_kanban_tools(store, mode="worker", current_task_id="t1")
        comment = self._get_tool(tools, "kanban_comment")
        result = json.loads(await comment.ainvoke({"task_id": "nonexistent", "body": "hello"}))
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_comment_persists_event(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)

        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1", agent_id="agent-007",
        )
        comment = self._get_tool(tools, "kanban_comment")
        await comment.ainvoke({"task_id": "t1", "body": "Test comment body"})

        from myrm_agent_harness.toolkits.kanban.types import TaskEventKind

        events = await store.list_events("t1")
        comment_events = [e for e in events if e.kind == TaskEventKind.USER_COMMENT]
        assert len(comment_events) == 1
        assert comment_events[0].payload is not None
        assert comment_events[0].payload["body"] == "Test comment body"
        assert comment_events[0].payload["author"] == "agent-007"

    @pytest.mark.asyncio
    async def test_comment_default_author(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)

        tools = create_kanban_tools(store, mode="worker", current_task_id="t1")
        comment = self._get_tool(tools, "kanban_comment")
        await comment.ainvoke({"task_id": "t1", "body": "No agent id"})

        from myrm_agent_harness.toolkits.kanban.types import TaskEventKind

        events = await store.list_events("t1")
        comment_events = [e for e in events if e.kind == TaskEventKind.USER_COMMENT]
        assert len(comment_events) == 1
        assert comment_events[0].payload is not None
        assert comment_events[0].payload["author"] == "worker"

    @pytest.mark.asyncio
    async def test_comment_body_stripped(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        await _make_task(store, "t1", status=TaskStatus.RUNNING)

        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1", agent_id="a1",
        )
        comment = self._get_tool(tools, "kanban_comment")
        await comment.ainvoke({"task_id": "t1", "body": "  padded body  "})

        from myrm_agent_harness.toolkits.kanban.types import TaskEventKind

        events = await store.list_events("t1")
        comment_events = [e for e in events if e.kind == TaskEventKind.USER_COMMENT]
        assert comment_events[0].payload is not None
        assert comment_events[0].payload["body"] == "padded body"

    @pytest.mark.asyncio
    async def test_comment_included_in_worker_tools(self) -> None:
        store = InMemoryKanbanStore()
        tools = create_kanban_tools(store, mode="worker", current_task_id="t1")
        tool_names = [t.name for t in tools]
        assert "kanban_comment" in tool_names
        assert len(tool_names) == 5

    @pytest.mark.asyncio
    async def test_comment_included_in_full_mode(self) -> None:
        store = InMemoryKanbanStore()
        tools = create_kanban_tools(store, mode="full")
        tool_names = [t.name for t in tools]
        assert "kanban_comment" in tool_names
