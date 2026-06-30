"""Tests for build_task_context — worker context assembly.

Covers: basic context, prior attempts, parent results + handoff metadata,
user comments, field truncation, and edge cases.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.kanban.context_builder import (
    _cap,
    build_multimodal_query,
    build_task_context,
)
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    KanbanBoard,
    KanbanTask,
    TaskAttachment,
    TaskEventKind,
    TaskRunOutcome,
    TaskStatus,
)


@pytest.fixture
def store() -> InMemoryKanbanStore:
    return InMemoryKanbanStore()


@pytest.fixture
def board() -> KanbanBoard:
    return KanbanBoard(board_id="b1", name="Test Board")


@pytest.fixture
async def basic_task(store: InMemoryKanbanStore, board: KanbanBoard) -> KanbanTask:
    await store.save_board(board)
    task = KanbanTask(
        task_id="t1",
        board_id="b1",
        title="Fix login bug",
        description="Users report login fails on mobile Safari.",
        status=TaskStatus.READY,
    )
    return await store.save_task(task)


class TestCap:
    def test_empty_string(self) -> None:
        assert _cap("") == ""

    def test_none(self) -> None:
        assert _cap(None) == ""

    def test_within_limit(self) -> None:
        assert _cap("hello", 10) == "hello"

    def test_exact_limit(self) -> None:
        assert _cap("hello", 5) == "hello"

    def test_exceeds_limit(self) -> None:
        result = _cap("hello world", 5)
        assert result.startswith("hello")
        assert "6 chars omitted" in result

    def test_strips_whitespace(self) -> None:
        assert _cap("  hello  ") == "hello"


class TestBuildTaskContext:
    @pytest.mark.asyncio
    async def test_unknown_task_raises(self, store: InMemoryKanbanStore) -> None:
        with pytest.raises(ValueError, match="Unknown task"):
            await build_task_context(store, "nonexistent")

    @pytest.mark.asyncio
    async def test_basic_context(
        self, store: InMemoryKanbanStore, basic_task: KanbanTask,
    ) -> None:
        ctx = await build_task_context(store, "t1")
        assert "# Task: Fix login bug" in ctx
        assert "Status: ready" in ctx
        assert "Priority: normal" in ctx
        assert "## Description" in ctx
        assert "mobile Safari" in ctx

    @pytest.mark.asyncio
    async def test_agent_id_shown(
        self, store: InMemoryKanbanStore, basic_task: KanbanTask,
    ) -> None:
        basic_task.agent_id = "agent-007"
        await store.save_task(basic_task)
        ctx = await build_task_context(store, "t1")
        assert "agent-007" in ctx

    @pytest.mark.asyncio
    async def test_no_description(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        await store.save_board(board)
        task = KanbanTask(
            task_id="t2", board_id="b1", title="No desc task",
            status=TaskStatus.READY,
        )
        await store.save_task(task)
        ctx = await build_task_context(store, "t2")
        assert "## Description" not in ctx

    @pytest.mark.asyncio
    async def test_prior_attempts(
        self, store: InMemoryKanbanStore, basic_task: KanbanTask,
    ) -> None:
        run = await store.create_run("t1", "w1")
        await store.complete_run(
            run.run_id, TaskRunOutcome.CRASHED, error="timeout",
        )
        ctx = await build_task_context(store, "t1")
        assert "## Prior attempts" in ctx
        assert "Attempt 1" in ctx
        assert "crashed" in ctx
        assert "timeout" in ctx

    @pytest.mark.asyncio
    async def test_prior_attempts_with_summary(
        self, store: InMemoryKanbanStore, basic_task: KanbanTask,
    ) -> None:
        run = await store.create_run("t1", "w1")
        await store.complete_run(
            run.run_id, TaskRunOutcome.COMPLETED, summary="Fixed the bug",
        )
        ctx = await build_task_context(store, "t1")
        assert "Fixed the bug" in ctx

    @pytest.mark.asyncio
    async def test_many_attempts_truncated(
        self, store: InMemoryKanbanStore, basic_task: KanbanTask,
    ) -> None:
        for i in range(8):
            run = await store.create_run("t1", "w1")
            await store.complete_run(
                run.run_id, TaskRunOutcome.CRASHED, error=f"error-{i}",
            )
        ctx = await build_task_context(store, "t1")
        assert "3 earlier attempts omitted" in ctx

    @pytest.mark.asyncio
    async def test_parent_results(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        await store.save_board(board)
        parent = KanbanTask(
            task_id="p1", board_id="b1", title="Parent Task",
            status=TaskStatus.COMPLETED, result="Parent completed successfully",
        )
        await store.save_task(parent)
        child = KanbanTask(
            task_id="c1", board_id="b1", title="Child Task",
            status=TaskStatus.READY,
        )
        await store.save_task(child)
        await store.add_edge("p1", "c1")

        ctx = await build_task_context(store, "c1")
        assert "## Parent task results" in ctx
        assert "Parent Task" in ctx
        assert "Parent completed successfully" in ctx

    @pytest.mark.asyncio
    async def test_parent_no_result(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        await store.save_board(board)
        parent = KanbanTask(
            task_id="p2", board_id="b1", title="Empty Parent",
            status=TaskStatus.COMPLETED,
        )
        await store.save_task(parent)
        child = KanbanTask(
            task_id="c2", board_id="b1", title="Child Task 2",
            status=TaskStatus.READY,
        )
        await store.save_task(child)
        await store.add_edge("p2", "c2")

        ctx = await build_task_context(store, "c2")
        assert "(no result recorded)" in ctx

    @pytest.mark.asyncio
    async def test_non_terminal_parent_excluded(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        await store.save_board(board)
        parent = KanbanTask(
            task_id="p3", board_id="b1", title="Running Parent",
            status=TaskStatus.RUNNING,
        )
        await store.save_task(parent)
        child = KanbanTask(
            task_id="c3", board_id="b1", title="Child Task 3",
            status=TaskStatus.READY,
        )
        await store.save_task(child)
        await store.add_edge("p3", "c3")

        ctx = await build_task_context(store, "c3")
        assert "## Parent task results" not in ctx

    @pytest.mark.asyncio
    async def test_user_comments(
        self, store: InMemoryKanbanStore, basic_task: KanbanTask,
    ) -> None:
        await store.append_event(
            "t1", TaskEventKind.USER_COMMENT,
            payload={"body": "Please fix ASAP", "author": "alice"},
        )
        ctx = await build_task_context(store, "t1")
        assert "## Comments" in ctx
        assert "@alice" in ctx
        assert "Please fix ASAP" in ctx

    @pytest.mark.asyncio
    async def test_many_comments_truncated(
        self, store: InMemoryKanbanStore, basic_task: KanbanTask,
    ) -> None:
        for i in range(25):
            await store.append_event(
                "t1", TaskEventKind.USER_COMMENT,
                payload={"body": f"comment-{i}", "author": "bot"},
            )
        ctx = await build_task_context(store, "t1")
        assert "5 earlier comments omitted" in ctx

    @pytest.mark.asyncio
    async def test_non_comment_events_excluded(
        self, store: InMemoryKanbanStore, basic_task: KanbanTask,
    ) -> None:
        await store.append_event("t1", TaskEventKind.CREATED)
        await store.append_event("t1", TaskEventKind.CLAIMED)
        ctx = await build_task_context(store, "t1")
        assert "## Comments" not in ctx

    @pytest.mark.asyncio
    async def test_parent_handoff_metadata(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        await store.save_board(board)
        parent = KanbanTask(
            task_id="ph1", board_id="b1", title="Impl Task",
            status=TaskStatus.COMPLETED,
            result="Implemented login feature",
            metadata={"handoff": {"changed_files": ["auth.py"], "verification": ["pytest tests/auth/"]}},
        )
        await store.save_task(parent)
        child = KanbanTask(
            task_id="ch1", board_id="b1", title="Review Task",
            status=TaskStatus.READY,
        )
        await store.save_task(child)
        await store.add_edge("ph1", "ch1")

        ctx = await build_task_context(store, "ch1")
        assert "Handoff:" in ctx
        assert "auth.py" in ctx
        assert "pytest tests/auth/" in ctx

    @pytest.mark.asyncio
    async def test_parent_no_handoff_metadata(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        await store.save_board(board)
        parent = KanbanTask(
            task_id="ph2", board_id="b1", title="Simple Task",
            status=TaskStatus.COMPLETED,
            result="Done",
        )
        await store.save_task(parent)
        child = KanbanTask(
            task_id="ch2", board_id="b1", title="Next Task",
            status=TaskStatus.READY,
        )
        await store.save_task(child)
        await store.add_edge("ph2", "ch2")

        ctx = await build_task_context(store, "ch2")
        assert "Handoff:" not in ctx

    @pytest.mark.asyncio
    async def test_parent_handoff_empty_dict_excluded(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        """Empty dict {} is falsy — should NOT produce Handoff line."""
        await store.save_board(board)
        parent = KanbanTask(
            task_id="ph3", board_id="b1", title="Empty Handoff",
            status=TaskStatus.COMPLETED, result="Done",
            metadata={"handoff": {}},
        )
        await store.save_task(parent)
        child = KanbanTask(task_id="ch3", board_id="b1", title="Next", status=TaskStatus.READY)
        await store.save_task(child)
        await store.add_edge("ph3", "ch3")
        ctx = await build_task_context(store, "ch3")
        assert "Handoff:" not in ctx

    @pytest.mark.asyncio
    async def test_parent_handoff_non_dict_list_excluded(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        """handoff is a list — isinstance(dict) guard should exclude it."""
        await store.save_board(board)
        parent = KanbanTask(
            task_id="ph4", board_id="b1", title="List Handoff",
            status=TaskStatus.COMPLETED, result="Done",
            metadata={"handoff": ["file1.py", "file2.py"]},
        )
        await store.save_task(parent)
        child = KanbanTask(task_id="ch4", board_id="b1", title="Next", status=TaskStatus.READY)
        await store.save_task(child)
        await store.add_edge("ph4", "ch4")
        ctx = await build_task_context(store, "ch4")
        assert "Handoff:" not in ctx

    @pytest.mark.asyncio
    async def test_parent_handoff_non_dict_string_excluded(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        """handoff is a string — should be excluded."""
        await store.save_board(board)
        parent = KanbanTask(
            task_id="ph5", board_id="b1", title="Str Handoff",
            status=TaskStatus.COMPLETED, result="Done",
            metadata={"handoff": "just a string"},
        )
        await store.save_task(parent)
        child = KanbanTask(task_id="ch5", board_id="b1", title="Next", status=TaskStatus.READY)
        await store.save_task(child)
        await store.add_edge("ph5", "ch5")
        ctx = await build_task_context(store, "ch5")
        assert "Handoff:" not in ctx

    @pytest.mark.asyncio
    async def test_parent_metadata_without_handoff_key(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        """metadata exists but has no 'handoff' key."""
        await store.save_board(board)
        parent = KanbanTask(
            task_id="ph6", board_id="b1", title="No Handoff Key",
            status=TaskStatus.COMPLETED, result="Done",
            metadata={"other_key": 42},
        )
        await store.save_task(parent)
        child = KanbanTask(task_id="ch6", board_id="b1", title="Next", status=TaskStatus.READY)
        await store.save_task(child)
        await store.add_edge("ph6", "ch6")
        ctx = await build_task_context(store, "ch6")
        assert "Handoff:" not in ctx

    @pytest.mark.asyncio
    async def test_parent_handoff_chinese_readable(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        """Chinese chars in handoff should be directly readable (ensure_ascii=False)."""
        await store.save_board(board)
        parent = KanbanTask(
            task_id="ph7", board_id="b1", title="中文任务",
            status=TaskStatus.COMPLETED, result="完成",
            metadata={"handoff": {"changed_files": ["登录模块.py"]}},
        )
        await store.save_task(parent)
        child = KanbanTask(task_id="ch7", board_id="b1", title="Next", status=TaskStatus.READY)
        await store.save_task(child)
        await store.add_edge("ph7", "ch7")
        ctx = await build_task_context(store, "ch7")
        assert "登录模块.py" in ctx
        assert "\\u" not in ctx

    @pytest.mark.asyncio
    async def test_parent_handoff_large_capped(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        """Large handoff dict should be capped at 4000 chars."""
        await store.save_board(board)
        large_files = [f"module_{i}.py" for i in range(500)]
        parent = KanbanTask(
            task_id="ph8", board_id="b1", title="Large Handoff",
            status=TaskStatus.COMPLETED, result="Done",
            metadata={"handoff": {"changed_files": large_files}},
        )
        await store.save_task(parent)
        child = KanbanTask(task_id="ch8", board_id="b1", title="Next", status=TaskStatus.READY)
        await store.save_task(child)
        await store.add_edge("ph8", "ch8")
        ctx = await build_task_context(store, "ch8")
        assert "Handoff:" in ctx
        assert "chars omitted" in ctx

    @pytest.mark.asyncio
    async def test_multiple_parents_mixed_handoff(
        self, store: InMemoryKanbanStore, board: KanbanBoard,
    ) -> None:
        """Multiple parents: one with handoff, one without."""
        await store.save_board(board)
        p1 = KanbanTask(
            task_id="mp1", board_id="b1", title="Parent With Handoff",
            status=TaskStatus.COMPLETED, result="Done A",
            metadata={"handoff": {"api": "/v1/users"}},
        )
        p2 = KanbanTask(
            task_id="mp2", board_id="b1", title="Parent No Handoff",
            status=TaskStatus.COMPLETED, result="Done B",
        )
        await store.save_task(p1)
        await store.save_task(p2)
        child = KanbanTask(task_id="mc1", board_id="b1", title="Merger", status=TaskStatus.READY)
        await store.save_task(child)
        await store.add_edge("mp1", "mc1")
        await store.add_edge("mp2", "mc1")
        ctx = await build_task_context(store, "mc1")
        assert ctx.count("Handoff:") == 1
        assert "/v1/users" in ctx
        assert "Done A" in ctx
        assert "Done B" in ctx


class TestBuildMultimodalQuery:
    def test_no_attachments_returns_plain_text(self) -> None:
        assert build_multimodal_query("hello context", []) == "hello context"

    def test_image_with_vision_returns_blocks(self) -> None:
        att = TaskAttachment(
            file_id="f1",
            filename="shot.png",
            mime_type="image/png",
            size_bytes=2048,
            content_ref="https://host/files/f1",
        )
        result = build_multimodal_query("task body", [att], has_vision=True)
        assert isinstance(result, list)
        assert result[0] == {"type": "text", "text": "task body"}
        assert result[1] == {
            "type": "image_url",
            "image_url": {"url": "https://host/files/f1"},
        }

    def test_image_without_vision_degrades_to_text_hint(self) -> None:
        att = TaskAttachment(
            file_id="f1",
            filename="shot.png",
            mime_type="image/jpeg",
            size_bytes=5120,
            content_ref="https://host/files/f1",
        )
        result = build_multimodal_query("task body", [att], has_vision=False)
        assert isinstance(result, list)
        hint = result[1]["text"]  # type: ignore[index]
        assert "Attached image: shot.png" in hint
        assert "model lacks vision" in hint
        assert "5KB" in hint

    def test_document_attachment_appends_text_block(self) -> None:
        att = TaskAttachment(
            file_id="f2",
            filename="spec.pdf",
            mime_type="application/pdf",
            size_bytes=10240,
            content_ref="vault://spec-uuid",
        )
        result = build_multimodal_query("ctx", [att])
        assert isinstance(result, list)
        doc_block = result[1]["text"]  # type: ignore[index]
        assert "Attached file: spec.pdf" in doc_block
        assert "application/pdf" in doc_block
        assert "ref=vault://spec-uuid" in doc_block

    def test_mixed_image_and_document(self) -> None:
        image = TaskAttachment(
            file_id="img", filename="ui.png", mime_type="image/png",
            size_bytes=100, content_ref="http://x/img",
        )
        doc = TaskAttachment(
            file_id="doc", filename="notes.txt", mime_type="text/plain",
            size_bytes=200, content_ref="http://x/doc",
        )
        result = build_multimodal_query("mixed", [image, doc], has_vision=True)
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[1]["type"] == "image_url"
        assert "Attached file: notes.txt" in result[2]["text"]  # type: ignore[index]
