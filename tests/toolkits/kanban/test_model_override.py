"""Tests for per-task model override feature.

Covers: KanbanTask.model_override, kanban_add_task model parameter,
to_dict serialization, and store round-trip persistence.
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
)


async def _make_board(store: InMemoryKanbanStore, board_id: str = "b1") -> KanbanBoard:
    board = KanbanBoard(board_id=board_id, name=f"Board {board_id}")
    return await store.save_board(board)


# ---------------------------------------------------------------------------
# KanbanTask dataclass
# ---------------------------------------------------------------------------


class TestKanbanTaskModelOverride:
    def test_default_none(self) -> None:
        task = KanbanTask(task_id="t1", board_id="b1", title="Test")
        assert task.model_override is None

    def test_assigned_model(self) -> None:
        task = KanbanTask(
            task_id="t1",
            board_id="b1",
            title="Test",
            model_override="anthropic/claude-sonnet-4",
        )
        assert task.model_override == "anthropic/claude-sonnet-4"

    def test_to_dict_includes_model_override(self) -> None:
        task = KanbanTask(
            task_id="t1",
            board_id="b1",
            title="Test",
            model_override="openai/gpt-4o",
        )
        d = task.to_dict()
        assert d["model_override"] == "openai/gpt-4o"

    def test_to_dict_none_model_override(self) -> None:
        task = KanbanTask(task_id="t1", board_id="b1", title="Test")
        d = task.to_dict()
        assert d["model_override"] is None


# ---------------------------------------------------------------------------
# Store round-trip
# ---------------------------------------------------------------------------


class TestModelOverrideStoreRoundTrip:
    @pytest.mark.asyncio
    async def test_save_get_preserves_model(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        task = KanbanTask(
            task_id="t1",
            board_id="b1",
            title="Test",
            model_override="minimax/abab6.5s",
        )
        await store.save_task(task)
        fetched = await store.get_task("t1")
        assert fetched is not None
        assert fetched.model_override == "minimax/abab6.5s"

    @pytest.mark.asyncio
    async def test_save_get_none_model(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        task = KanbanTask(task_id="t1", board_id="b1", title="Test")
        await store.save_task(task)
        fetched = await store.get_task("t1")
        assert fetched is not None
        assert fetched.model_override is None

    @pytest.mark.asyncio
    async def test_update_model_override(self) -> None:
        store = InMemoryKanbanStore()
        await _make_board(store)
        task = KanbanTask(
            task_id="t1",
            board_id="b1",
            title="Test",
            model_override="openai/gpt-4o",
        )
        await store.save_task(task)
        task.model_override = None
        await store.save_task(task)
        fetched = await store.get_task("t1")
        assert fetched is not None
        assert fetched.model_override is None


# ---------------------------------------------------------------------------
# kanban_add_task model parameter
# ---------------------------------------------------------------------------


class TestKanbanAddTaskModel:
    @pytest.fixture
    def store(self) -> InMemoryKanbanStore:
        return InMemoryKanbanStore()

    @pytest.fixture
    def tool_map(self, store: InMemoryKanbanStore) -> dict[str, object]:
        tools = create_kanban_tools(store=store, agent_id="agent-1")
        return {t.name: t for t in tools}

    @pytest.mark.asyncio
    async def test_add_task_with_model(
        self,
        store: InMemoryKanbanStore,
        tool_map: dict,
    ) -> None:
        await _make_board(store)
        add_fn = tool_map["kanban_add_task"]
        result = json.loads(
            await add_fn.coroutine(
                title="Translate docs",
                board_id="b1",
                model="anthropic/claude-sonnet-4",
            )
        )
        assert result["status"] == "added"
        assert result["task"]["model_override"] == "anthropic/claude-sonnet-4"
        task = await store.get_task(result["task"]["task_id"])
        assert task is not None
        assert task.model_override == "anthropic/claude-sonnet-4"

    @pytest.mark.asyncio
    async def test_add_task_without_model(
        self,
        store: InMemoryKanbanStore,
        tool_map: dict,
    ) -> None:
        await _make_board(store)
        add_fn = tool_map["kanban_add_task"]
        result = json.loads(
            await add_fn.coroutine(
                title="Normal task",
                board_id="b1",
            )
        )
        assert result["status"] == "added"
        assert result["task"]["model_override"] is None
        task = await store.get_task(result["task"]["task_id"])
        assert task is not None
        assert task.model_override is None
