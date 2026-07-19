"""Tests for task-level extra_skill_ids feature.

Covers: KanbanTask.extra_skill_ids, DecomposeChildSpec.extra_skill_ids,
kanban_add_task skills parameter,
to_dict serialization, and skill parsing logic.
"""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.toolkits.kanban.kanban_agent_tools import (
    create_kanban_tools,
)
from myrm_agent_harness.toolkits.kanban.protocols import DecomposeChildSpec
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


class TestKanbanTaskExtraSkillIds:
    def test_default_empty(self) -> None:
        task = KanbanTask(task_id="t1", board_id="b1", title="Test")
        assert task.extra_skill_ids == []

    def test_assigned_skills(self) -> None:
        task = KanbanTask(
            task_id="t1", board_id="b1", title="Test",
            extra_skill_ids=["translation", "security-audit"],
        )
        assert task.extra_skill_ids == ["translation", "security-audit"]

    def test_to_dict_includes_skills(self) -> None:
        task = KanbanTask(
            task_id="t1", board_id="b1", title="Test",
            extra_skill_ids=["web-search"],
        )
        d = task.to_dict()
        assert d["extra_skill_ids"] == ["web-search"]

    def test_to_dict_empty_skills(self) -> None:
        task = KanbanTask(task_id="t1", board_id="b1", title="Test")
        d = task.to_dict()
        assert d["extra_skill_ids"] == []


# ---------------------------------------------------------------------------
# DecomposeChildSpec
# ---------------------------------------------------------------------------


class TestDecomposeChildSpecSkills:
    def test_default_empty(self) -> None:
        spec = DecomposeChildSpec(title="Child", body="Body")
        assert spec.extra_skill_ids == ()

    def test_assigned_skills(self) -> None:
        spec = DecomposeChildSpec(
            title="Child", body="Body",
            extra_skill_ids=("translation", "code-review"),
        )
        assert spec.extra_skill_ids == ("translation", "code-review")

    def test_frozen(self) -> None:
        spec = DecomposeChildSpec(
            title="Child", body="Body",
            extra_skill_ids=("a",),
        )
        with pytest.raises(AttributeError):
            spec.extra_skill_ids = ("b",)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# kanban_add_task skills parameter
# ---------------------------------------------------------------------------


class TestKanbanAddTaskSkills:
    @pytest.fixture
    def store(self) -> InMemoryKanbanStore:
        return InMemoryKanbanStore()

    @pytest.fixture
    def tool_map(self, store: InMemoryKanbanStore) -> dict[str, object]:
        tools = create_kanban_tools(store=store, agent_id="agent-1")
        return {t.name: t for t in tools}

    @pytest.mark.asyncio
    async def test_add_task_with_skills(
        self, store: InMemoryKanbanStore, tool_map: dict,
    ) -> None:
        await _make_board(store)
        add_fn = tool_map["kanban_add_task"]
        result = json.loads(await add_fn.coroutine(
            title="Translate docs",
            board_id="b1",
            skills="translation, security-audit",
        ))
        assert result["status"] == "added"
        task = await store.get_task(result["task"]["task_id"])
        assert task is not None
        assert task.extra_skill_ids == ["translation", "security-audit"]

    @pytest.mark.asyncio
    async def test_add_task_without_skills(
        self, store: InMemoryKanbanStore, tool_map: dict,
    ) -> None:
        await _make_board(store)
        add_fn = tool_map["kanban_add_task"]
        result = json.loads(await add_fn.coroutine(
            title="Normal task", board_id="b1",
        ))
        task = await store.get_task(result["task"]["task_id"])
        assert task is not None
        assert task.extra_skill_ids == []

    @pytest.mark.asyncio
    async def test_add_task_skills_dedup(
        self, store: InMemoryKanbanStore, tool_map: dict,
    ) -> None:
        await _make_board(store)
        add_fn = tool_map["kanban_add_task"]
        result = json.loads(await add_fn.coroutine(
            title="Dedup task", board_id="b1",
            skills="a, b, a, c, b",
        ))
        task = await store.get_task(result["task"]["task_id"])
        assert task is not None
        assert task.extra_skill_ids == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_add_task_skills_strip_empty(
        self, store: InMemoryKanbanStore, tool_map: dict,
    ) -> None:
        await _make_board(store)
        add_fn = tool_map["kanban_add_task"]
        result = json.loads(await add_fn.coroutine(
            title="Strip task", board_id="b1",
            skills=" , ,  x  , , y , ",
        ))
        task = await store.get_task(result["task"]["task_id"])
        assert task is not None
        assert task.extra_skill_ids == ["x", "y"]


# ---------------------------------------------------------------------------
# Persistence round-trip via to_dict
# ---------------------------------------------------------------------------


class TestToDict:
    def test_to_dict_round_trip(self) -> None:
        task = KanbanTask(
            task_id="t1", board_id="b1", title="Test",
            extra_skill_ids=["a", "b", "c"],
        )
        d = task.to_dict()
        assert d["extra_skill_ids"] == ["a", "b", "c"]
        serialized = json.dumps(d)
        restored = json.loads(serialized)
        assert restored["extra_skill_ids"] == ["a", "b", "c"]
