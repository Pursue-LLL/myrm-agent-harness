"""Test DiffCollectorObserver and _compute_unified_diff.

Verifies unified diff computation, SSE event emission via ToolProgressSink,
truncation for large diffs, and silent skip when no sink is available.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.observers.diff_collector import (
    _MAX_DIFF_LINES,
    DiffCollectorObserver,
    _compute_unified_diff,
)

# ---------------------------------------------------------------------------
# _compute_unified_diff
# ---------------------------------------------------------------------------


class TestComputeUnifiedDiff:
    def test_new_file(self):
        diff, added, removed, count = _compute_unified_diff("", "line1\nline2\n", "test.py", is_new=True)
        assert added == 2
        assert removed == 0
        assert count > 0
        assert "/dev/null" in diff
        assert "b/test.py" in diff

    def test_modify_file(self):
        old = "line1\nline2\nline3\n"
        new = "line1\nmodified\nline3\nline4\n"
        diff, added, removed, _count = _compute_unified_diff(old, new, "src/app.py", is_new=False)
        assert added >= 1
        assert removed >= 1
        assert "a/src/app.py" in diff
        assert "b/src/app.py" in diff

    def test_identical_content(self):
        content = "same\n"
        diff, added, removed, count = _compute_unified_diff(content, content, "f.txt", is_new=False)
        assert diff == ""
        assert added == 0
        assert removed == 0
        assert count == 0

    def test_empty_to_empty(self):
        diff, _added, _removed, count = _compute_unified_diff("", "", "f.txt", is_new=True)
        assert diff == ""
        assert count == 0


# ---------------------------------------------------------------------------
# DiffCollectorObserver — event emission
# ---------------------------------------------------------------------------


class TestDiffCollectorObserver:
    @pytest.fixture()
    def observer(self) -> DiffCollectorObserver:
        return DiffCollectorObserver()

    @pytest.mark.asyncio
    async def test_on_file_created_emits_event(self, observer: DiffCollectorObserver):
        mock_sink = AsyncMock()
        with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=mock_sink):
            await observer.on_file_created("new.py", "print('hello')\n")

        mock_sink.emit.assert_awaited_once()
        event = mock_sink.emit.call_args[0][0]
        assert event["type"] == "file_diff"
        data = event["data"]
        assert data["path"] == "new.py"
        assert data["is_new"] is True
        assert data["lines_added"] >= 1
        assert data["truncated"] is False
        assert data["diff"]

    @pytest.mark.asyncio
    async def test_on_file_modified_emits_event(self, observer: DiffCollectorObserver):
        mock_sink = AsyncMock()
        with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=mock_sink):
            await observer.on_file_modified("app.py", "old\n", "new\n")

        mock_sink.emit.assert_awaited_once()
        event = mock_sink.emit.call_args[0][0]
        assert event["data"]["path"] == "app.py"
        assert event["data"]["is_new"] is False

    @pytest.mark.asyncio
    async def test_skip_when_no_sink(self, observer: DiffCollectorObserver):
        with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=None):
            await observer.on_file_created("test.py", "content\n")

    @pytest.mark.asyncio
    async def test_skip_empty_content(self, observer: DiffCollectorObserver):
        mock_sink = AsyncMock()
        with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=mock_sink):
            await observer.on_file_created("empty.py", "")

        mock_sink.emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skip_identical_modification(self, observer: DiffCollectorObserver):
        mock_sink = AsyncMock()
        with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=mock_sink):
            await observer.on_file_modified("same.py", "content\n", "content\n")

        mock_sink.emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_truncation_for_large_diff(self, observer: DiffCollectorObserver):
        mock_sink = AsyncMock()
        large_content = "\n".join(f"line_{i}" for i in range(_MAX_DIFF_LINES + 500))
        with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=mock_sink):
            await observer.on_file_created("big.py", large_content)

        mock_sink.emit.assert_awaited_once()
        data = mock_sink.emit.call_args[0][0]["data"]
        assert data["truncated"] is True
        assert data["diff"]
        assert len(data["diff"].splitlines()) <= _MAX_DIFF_LINES
        assert data["lines_added"] > 0

    @pytest.mark.asyncio
    async def test_emit_exception_is_caught(self, observer: DiffCollectorObserver):
        """Exception during emit is caught and logged, not raised."""
        mock_sink = AsyncMock()
        mock_sink.emit.side_effect = RuntimeError("sink broken")
        with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink", return_value=mock_sink):
            await observer.on_file_created("err.py", "content\n")

    @pytest.mark.asyncio
    async def test_on_file_viewed_is_noop(self, observer: DiffCollectorObserver):
        await observer.on_file_viewed("some.py")

    @pytest.mark.asyncio
    async def test_modify_ignores_blank_create_initial_snap_for_base(
        self, observer: DiffCollectorObserver,
    ) -> None:
        """When the first snapshot is a spurious CREATE (no original), MODIFY must not diff from /dev/null."""
        from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
            FileSnapshot,
            SnapshotOp,
            SnapshotStore,
            set_current_message_id,
        )

        SnapshotStore.reset()
        set_current_message_id("msg-diff-fallback")
        store = SnapshotStore.get()
        try:
            store.record(
                "chat-diff-fallback",
                "msg-diff-fallback",
                FileSnapshot(path="fallback.txt", operation=SnapshotOp.CREATE, original_content=None),
            )
            mock_sink = AsyncMock()
            with patch(
                "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
                return_value=mock_sink,
            ), patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer._get_session_id",
                return_value="chat-diff-fallback",
            ):
                await observer.on_file_modified("fallback.txt", "line1\n", "line1\nnew\n")

            mock_sink.emit.assert_awaited_once()
            data = mock_sink.emit.call_args[0][0]["data"]
            assert data["is_new"] is False
            diff = str(data["diff"])
            assert "/dev/null" not in diff
            assert "fallback.txt" in diff
        finally:
            SnapshotStore.reset()


def test_snapshot_initial_snap_scoped_per_message_id() -> None:
    """Turn-local message_id must not reuse another turn's first snapshot for the same path."""
    from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
        FileSnapshot,
        SnapshotOp,
        SnapshotStore,
        set_current_message_id,
    )

    SnapshotStore.reset()
    store = SnapshotStore.get()
    try:
        set_current_message_id("m1")
        store.record(
            "chat-x",
            "m1",
            FileSnapshot("p.txt", operation=SnapshotOp.CREATE, original_content=None),
        )
        set_current_message_id("m2")
        store.record(
            "chat-x",
            "m2",
            FileSnapshot("p.txt", operation=SnapshotOp.MODIFY, original_content="before\n"),
        )
        first_m1 = store.get_initial_file_snapshot("chat-x", "m1", "p.txt")
        first_m2 = store.get_initial_file_snapshot("chat-x", "m2", "p.txt")
        assert first_m1 is not None and first_m1.operation == SnapshotOp.CREATE
        assert first_m2 is not None and first_m2.operation == SnapshotOp.MODIFY
    finally:
        SnapshotStore.reset()


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------


def test_module_export():
    from myrm_agent_harness.agent.meta_tools.file_ops.observers import DiffCollectorObserver as Exported

    assert Exported is DiffCollectorObserver


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
