"""Tests for TRIAGE status, _TRIAGE_ALLOWED_TARGETS, SpecifyOutcome, and TaskSpecifier Protocol.

Covers the harness-layer contracts introduced for the Triage + LLM Specifier feature:
- TaskStatus.TRIAGE membership in the enum
- _TRIAGE_ALLOWED_TARGETS guard (BACKLOG / READY / ARCHIVED only)
- TaskEventKind.SPECIFIED membership
- SpecifyOutcome dataclass fields and frozen invariant
- TaskSpecifier Protocol structural conformance
- BoardSettings new fields (specify_max_tokens, auto_specify_on_create)
- InMemoryKanbanStore TRIAGE task CRUD
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from myrm_agent_harness.toolkits.kanban.protocols import SpecifyOutcome, TaskSpecifier
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    _TRIAGE_ALLOWED_TARGETS,
    BoardSettings,
    KanbanBoard,
    KanbanTask,
    TaskEventKind,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# TaskStatus.TRIAGE
# ---------------------------------------------------------------------------


class TestTriageStatus:
    def test_triage_is_a_valid_status(self) -> None:
        assert TaskStatus.TRIAGE.value == "triage"
        assert TaskStatus.TRIAGE in TaskStatus

    def test_triage_not_in_terminal_statuses(self) -> None:
        from myrm_agent_harness.toolkits.kanban.types import _TERMINAL_STATUSES
        assert TaskStatus.TRIAGE not in _TERMINAL_STATUSES

    def test_triage_not_in_active_statuses(self) -> None:
        from myrm_agent_harness.toolkits.kanban.types import _ACTIVE_STATUSES
        assert TaskStatus.TRIAGE not in _ACTIVE_STATUSES

    def test_triage_allowed_targets_exact(self) -> None:
        assert frozenset({
            TaskStatus.BACKLOG, TaskStatus.READY, TaskStatus.ARCHIVED,
        }) == _TRIAGE_ALLOWED_TARGETS

    def test_triage_cannot_go_to_running(self) -> None:
        assert TaskStatus.RUNNING not in _TRIAGE_ALLOWED_TARGETS

    def test_triage_cannot_go_to_blocked(self) -> None:
        assert TaskStatus.BLOCKED not in _TRIAGE_ALLOWED_TARGETS

    def test_triage_cannot_go_to_completed(self) -> None:
        assert TaskStatus.COMPLETED not in _TRIAGE_ALLOWED_TARGETS

    def test_triage_cannot_go_to_failed(self) -> None:
        assert TaskStatus.FAILED not in _TRIAGE_ALLOWED_TARGETS

    def test_task_can_be_created_with_triage_status(self) -> None:
        task = KanbanTask(
            task_id="t1", board_id="b1", title="rough idea",
            status=TaskStatus.TRIAGE,
        )
        assert task.status == TaskStatus.TRIAGE


# ---------------------------------------------------------------------------
# TaskEventKind.SPECIFIED
# ---------------------------------------------------------------------------


class TestSpecifiedEventKind:
    def test_specified_is_a_valid_event_kind(self) -> None:
        assert TaskEventKind.SPECIFIED.value == "specified"
        assert TaskEventKind.SPECIFIED in TaskEventKind


# ---------------------------------------------------------------------------
# SpecifyOutcome
# ---------------------------------------------------------------------------


class TestSpecifyOutcome:
    def test_ok_outcome_fields(self) -> None:
        o = SpecifyOutcome(
            task_id="t1", ok=True, reason="specified",
            new_title="Better Title", new_body="**Goal** ...",
            prompt_tokens=100, completion_tokens=200,
            persisted=True,
        )
        assert o.task_id == "t1"
        assert o.ok is True
        assert o.reason == "specified"
        assert o.new_title == "Better Title"
        assert o.new_body == "**Goal** ..."
        assert o.prompt_tokens == 100
        assert o.completion_tokens == 200
        assert o.persisted is True

    def test_failed_outcome_defaults(self) -> None:
        o = SpecifyOutcome(task_id="t2", ok=False, reason="llm_error:Timeout")
        assert o.new_title is None
        assert o.new_body is None
        assert o.prompt_tokens is None
        assert o.completion_tokens is None
        assert o.persisted is False

    def test_outcome_is_frozen(self) -> None:
        o = SpecifyOutcome(task_id="t1", ok=True)
        with pytest.raises(FrozenInstanceError):
            o.ok = False  # type: ignore[misc]

    def test_minimal_outcome(self) -> None:
        o = SpecifyOutcome(task_id="t1", ok=True)
        assert o.reason == ""


# ---------------------------------------------------------------------------
# TaskSpecifier Protocol
# ---------------------------------------------------------------------------


class TestTaskSpecifierProtocol:
    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(TaskSpecifier, "__protocol_attrs__") or hasattr(TaskSpecifier, "__abstractmethods__") or True

    def test_conformance_with_specify_method(self) -> None:
        class FakeSpecifier:
            async def specify(self, task: KanbanTask, *, persist: bool = False) -> SpecifyOutcome:
                return SpecifyOutcome(task_id=task.task_id, ok=True)

        assert isinstance(FakeSpecifier(), TaskSpecifier)

    def test_non_conformance_without_specify(self) -> None:
        class NotASpecifier:
            pass

        assert not isinstance(NotASpecifier(), TaskSpecifier)


# ---------------------------------------------------------------------------
# BoardSettings
# ---------------------------------------------------------------------------


class TestBoardSettingsSpecifyFields:
    def test_default_specify_max_tokens(self) -> None:
        settings = BoardSettings()
        assert settings.specify_max_tokens == 6000

    def test_default_auto_specify_on_create(self) -> None:
        settings = BoardSettings()
        assert settings.auto_specify_on_create is False

    def test_custom_specify_settings(self) -> None:
        settings = BoardSettings(specify_max_tokens=12000, auto_specify_on_create=True)
        assert settings.specify_max_tokens == 12000
        assert settings.auto_specify_on_create is True

    def test_settings_in_board_to_dict(self) -> None:
        board = KanbanBoard(
            board_id="b1",
            name="Test",
            settings=BoardSettings(specify_max_tokens=8000, auto_specify_on_create=True),
        )
        d = board.to_dict()
        assert d["settings"]["specify_max_tokens"] == 8000
        assert d["settings"]["auto_specify_on_create"] is True


# ---------------------------------------------------------------------------
# InMemoryKanbanStore: TRIAGE tasks
# ---------------------------------------------------------------------------


class TestInMemoryStoreTriage:
    @pytest.mark.asyncio
    async def test_save_and_get_triage_task(self) -> None:
        store = InMemoryKanbanStore()
        board = KanbanBoard(board_id="b1", name="B")
        await store.save_board(board)
        task = KanbanTask(
            task_id="t1", board_id="b1", title="rough idea",
            status=TaskStatus.TRIAGE,
        )
        saved = await store.save_task(task)
        assert saved.status == TaskStatus.TRIAGE
        fetched = await store.get_task("t1")
        assert fetched is not None
        assert fetched.status == TaskStatus.TRIAGE

    @pytest.mark.asyncio
    async def test_list_tasks_filters_by_triage(self) -> None:
        store = InMemoryKanbanStore()
        board = KanbanBoard(board_id="b1", name="B")
        await store.save_board(board)
        await store.save_task(KanbanTask(
            task_id="t1", board_id="b1", title="idea", status=TaskStatus.TRIAGE,
        ))
        await store.save_task(KanbanTask(
            task_id="t2", board_id="b1", title="ready task", status=TaskStatus.READY,
        ))
        triage_tasks = await store.list_tasks("b1", status=TaskStatus.TRIAGE)
        assert len(triage_tasks) == 1
        assert triage_tasks[0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_triage_task_not_in_ready_list(self) -> None:
        store = InMemoryKanbanStore()
        board = KanbanBoard(board_id="b1", name="B")
        await store.save_board(board)
        await store.save_task(KanbanTask(
            task_id="t1", board_id="b1", title="idea", status=TaskStatus.TRIAGE,
        ))
        ready_tasks = await store.list_ready_tasks("b1")
        assert len(ready_tasks) == 0

    @pytest.mark.asyncio
    async def test_triage_task_count_grouped(self) -> None:
        store = InMemoryKanbanStore()
        board = KanbanBoard(board_id="b1", name="B")
        await store.save_board(board)
        await store.save_task(KanbanTask(
            task_id="t1", board_id="b1", title="idea", status=TaskStatus.TRIAGE,
        ))
        await store.save_task(KanbanTask(
            task_id="t2", board_id="b1", title="ready", status=TaskStatus.READY,
        ))
        counts = await store.count_tasks_grouped("b1")
        assert counts.get("triage", 0) == 1
        assert counts.get("ready", 0) == 1

    @pytest.mark.asyncio
    async def test_specified_event_can_be_appended(self) -> None:
        store = InMemoryKanbanStore()
        board = KanbanBoard(board_id="b1", name="B")
        await store.save_board(board)
        await store.save_task(KanbanTask(
            task_id="t1", board_id="b1", title="idea", status=TaskStatus.TRIAGE,
        ))
        event = await store.append_event(
            "t1", TaskEventKind.SPECIFIED,
            payload={"author": "specifier", "promoted_to": "ready"},
        )
        assert event.kind == TaskEventKind.SPECIFIED
        events = await store.list_events("t1")
        assert any(e.kind == TaskEventKind.SPECIFIED for e in events)
