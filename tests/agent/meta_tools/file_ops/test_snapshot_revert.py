"""Tests for Snapshot + Revert system.

Covers: SnapshotStore, SnapshotObserver, RevertService, contextvars safety.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
    MAX_FILE_BYTES,
    MAX_STORE_BYTES,
    FileSnapshot,
    SnapshotObserver,
    SnapshotOp,
    SnapshotSkipReason,
    SnapshotStore,
    get_current_message_id,
    set_current_message_id,
)
from myrm_agent_harness.agent.meta_tools.file_ops.revert_service import RevertService


@pytest.fixture(autouse=True)
def reset_store():
    """Reset singleton between tests."""
    SnapshotStore.reset()
    yield
    SnapshotStore.reset()


class TestSnapshotStore:
    def test_singleton(self):
        s1 = SnapshotStore.get()
        s2 = SnapshotStore.get()
        assert s1 is s2

    def test_reset(self):
        s1 = SnapshotStore.get()
        SnapshotStore.reset()
        s2 = SnapshotStore.get()
        assert s1 is not s2

    def test_record_and_get(self):
        store = SnapshotStore.get()
        snap = FileSnapshot(path="/a.py", operation=SnapshotOp.MODIFY, original_content="old")
        assert store.record("s1", "m1", snap)
        assert store.get_message_snapshots("s1", "m1") == [snap]

    def test_record_create_no_content(self):
        store = SnapshotStore.get()
        snap = FileSnapshot(path="/new.py", operation=SnapshotOp.CREATE, original_content=None)
        assert store.record("s1", "m1", snap)
        assert snap.size_bytes == 0

    def test_file_size_limit(self):
        store = SnapshotStore.get()
        big_content = "x" * (MAX_FILE_BYTES + 1)
        snap = FileSnapshot(path="/big.py", operation=SnapshotOp.MODIFY, original_content=big_content)
        assert not store.record("s1", "m1", snap)

    def test_record_skipped_metadata(self):
        store = SnapshotStore.get()
        store.record_skipped("s1", "m1", "/big.py", SnapshotOp.MODIFY, SnapshotSkipReason.FILE_TOO_LARGE)
        snaps = store.get_message_snapshots("s1", "m1")
        assert len(snaps) == 1
        assert snaps[0].revertible is False
        assert snaps[0].skip_reason == SnapshotSkipReason.FILE_TOO_LARGE
        assert snaps[0].size_bytes == 0
        assert store.total_bytes == 0

    def test_record_skipped_dedup(self):
        store = SnapshotStore.get()
        store.record_skipped("s1", "m1", "/big.py", SnapshotOp.MODIFY, SnapshotSkipReason.FILE_TOO_LARGE)
        store.record_skipped("s1", "m1", "/big.py", SnapshotOp.MODIFY, SnapshotSkipReason.STORE_FULL)
        assert len(store.get_message_snapshots("s1", "m1")) == 1

    def test_total_store_limit(self):
        store = SnapshotStore.get()
        chunk = "x" * (MAX_FILE_BYTES - 1)
        count = 0
        while store.total_bytes + len(chunk.encode("utf-8")) <= MAX_STORE_BYTES:
            snap = FileSnapshot(path=f"/f{count}.py", operation=SnapshotOp.MODIFY, original_content=chunk)
            if not store.record("s1", f"m{count}", snap):
                break
            count += 1
        final_snap = FileSnapshot(path="/overflow.py", operation=SnapshotOp.MODIFY, original_content=chunk)
        assert not store.record("s1", "overflow", final_snap)

    def test_get_session_snapshots(self):
        store = SnapshotStore.get()
        store.record("s1", "m1", FileSnapshot("/a.py", SnapshotOp.MODIFY, "a"))
        store.record("s1", "m2", FileSnapshot("/b.py", SnapshotOp.MODIFY, "b"))
        session = store.get_session_snapshots("s1")
        assert "m1" in session
        assert "m2" in session

    def test_get_file_snapshot(self):
        store = SnapshotStore.get()
        snap1 = FileSnapshot("/a.py", SnapshotOp.MODIFY, "v1")
        snap2 = FileSnapshot("/a.py", SnapshotOp.MODIFY, "v2")
        store.record("s1", "m1", snap1)
        store.record("s1", "m1", snap2)
        result = store.get_file_snapshot("s1", "m1", "/a.py")
        assert result is not None
        assert result.original_content == "v2"

    def test_remove_message(self):
        store = SnapshotStore.get()
        store.record("s1", "m1", FileSnapshot("/a.py", SnapshotOp.MODIFY, "old"))
        assert store.total_bytes > 0
        removed = store.remove_message("s1", "m1")
        assert len(removed) == 1
        assert store.total_bytes == 0

    def test_clear_session(self):
        store = SnapshotStore.get()
        store.record("s1", "m1", FileSnapshot("/a.py", SnapshotOp.MODIFY, "a"))
        store.record("s1", "m2", FileSnapshot("/b.py", SnapshotOp.MODIFY, "b"))
        count = store.clear_session("s1")
        assert count == 2
        assert store.total_bytes == 0

    def test_empty_queries(self):
        store = SnapshotStore.get()
        assert store.get_message_snapshots("none", "none") == []
        assert store.get_session_snapshots("none") == {}
        assert store.get_file_snapshot("none", "none", "/a") is None

    @pytest.mark.asyncio
    async def test_persist_skipped_to_disk(self):
        store = SnapshotStore.get()
        store.record_skipped("s1", "m1", "/big.py", SnapshotOp.MODIFY, SnapshotSkipReason.FILE_TOO_LARGE)

        with tempfile.TemporaryDirectory() as tmpdir:
            await store.persist_to_disk(tmpdir, "s1", "m1")
            target = Path(tmpdir) / ".myrm/snapshots/s1/m1.json"
            data = json.loads(target.read_text("utf-8"))
            assert data[0]["skip_reason"] == "file_too_large"
            assert data[0]["original_content"] is None

            result = await SnapshotStore.load_from_disk(tmpdir, "s1")
            _, snaps = result[0]
            assert snaps[0].skip_reason == SnapshotSkipReason.FILE_TOO_LARGE
            assert snaps[0].revertible is False

    @pytest.mark.asyncio
    async def test_merge_skipped_from_disk(self):
        store = SnapshotStore.get()
        store.record_skipped("s1", "m1", "/big.py", SnapshotOp.MODIFY, SnapshotSkipReason.FILE_TOO_LARGE)
        with tempfile.TemporaryDirectory() as tmpdir:
            await store.persist_to_disk(tmpdir, "s1", "m1")

            SnapshotStore.reset()
            fresh = SnapshotStore.get()
            merged = await fresh.merge_session_from_disk(tmpdir, "s1")
            assert merged is True
            snaps = fresh.get_message_snapshots("s1", "m1")
            assert len(snaps) == 1
            assert snaps[0].revertible is False

    @pytest.mark.asyncio
    async def test_persist_to_disk(self):
        store = SnapshotStore.get()
        store.record("s1", "m1", FileSnapshot("/a.py", SnapshotOp.MODIFY, "content"))

        with tempfile.TemporaryDirectory() as tmpdir:
            await store.persist_to_disk(tmpdir, "s1", "m1")
            target = Path(tmpdir) / ".myrm/snapshots/s1/m1.json"
            assert target.is_file()
            data = json.loads(target.read_text("utf-8"))
            assert len(data) == 1
            assert data[0]["path"] == "/a.py"
            assert data[0]["original_content"] == "content"

    @pytest.mark.asyncio
    async def test_load_from_disk(self):
        store = SnapshotStore.get()
        store.record("s1", "m1", FileSnapshot("/a.py", SnapshotOp.MODIFY, "orig"))

        with tempfile.TemporaryDirectory() as tmpdir:
            await store.persist_to_disk(tmpdir, "s1", "m1")
            result = await SnapshotStore.load_from_disk(tmpdir, "s1")
            assert len(result) == 1
            msg_id, snaps = result[0]
            assert msg_id == "m1"
            assert snaps[0].path == "/a.py"
            assert snaps[0].original_content == "orig"

    @pytest.mark.asyncio
    async def test_merge_session_from_disk(self):
        SnapshotStore.reset()
        store = SnapshotStore.get()
        store.record("s1", "m1", FileSnapshot("/a.py", SnapshotOp.MODIFY, "orig"))
        with tempfile.TemporaryDirectory() as tmpdir:
            await store.persist_to_disk(tmpdir, "s1", "m1")

            SnapshotStore.reset()
            fresh = SnapshotStore.get()
            assert fresh.get_message_snapshots("s1", "m1") == []

            merged = await fresh.merge_session_from_disk(tmpdir, "s1")
            assert merged is True
            snaps = fresh.get_message_snapshots("s1", "m1")
            assert len(snaps) == 1
            assert snaps[0].original_content == "orig"


class TestContextVars:
    def test_set_and_get_message_id(self):
        set_current_message_id("test-msg-123")
        assert get_current_message_id() == "test-msg-123"

    def test_auto_generate_message_id(self):
        """In a fresh context, get_current_message_id generates a new msg_ ID."""
        import contextvars

        from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import _current_message_id

        ctx = contextvars.copy_context()

        def _set_none_and_get():
            _current_message_id.set(None)
            return get_current_message_id()

        msg_id = ctx.run(_set_none_and_get)
        assert msg_id.startswith("msg_")

    def test_isolation_between_contexts(self):
        """Different contextvars contexts should have independent message IDs."""
        import contextvars

        from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import _current_message_id

        results: list[str] = []

        def _set_and_get(val: str) -> str:
            _current_message_id.set(None)
            set_current_message_id(val)
            return get_current_message_id()

        ctx1 = contextvars.copy_context()
        ctx2 = contextvars.copy_context()
        results.append(ctx1.run(_set_and_get, "ctx1-msg"))
        results.append(ctx2.run(_set_and_get, "ctx2-msg"))
        assert results[0] == "ctx1-msg"
        assert results[1] == "ctx2-msg"


class TestSnapshotObserver:
    @pytest.mark.asyncio
    async def test_on_file_created(self):
        observer = SnapshotObserver()
        set_current_message_id("test-create")

        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer._get_session_id",
            return_value="test-session",
        ):
            await observer.on_file_created("/new.py", "content")

        store = SnapshotStore.get()
        snaps = store.get_message_snapshots("test-session", "test-create")
        assert len(snaps) == 1
        assert snaps[0].operation == SnapshotOp.CREATE
        assert snaps[0].original_content is None

    @pytest.mark.asyncio
    async def test_on_file_modified(self):
        observer = SnapshotObserver()
        set_current_message_id("test-modify")

        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer._get_session_id",
            return_value="test-session",
        ):
            await observer.on_file_modified("/a.py", "old-content", "new-content")

        store = SnapshotStore.get()
        snaps = store.get_message_snapshots("test-session", "test-modify")
        assert len(snaps) == 1
        assert snaps[0].operation == SnapshotOp.MODIFY
        assert snaps[0].original_content == "old-content"

    @pytest.mark.asyncio
    async def test_on_file_modified_skips_large_file(self):
        observer = SnapshotObserver()
        set_current_message_id("test-large")

        big = "x" * (MAX_FILE_BYTES + 1)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer._get_session_id",
            return_value="test-session",
        ):
            await observer.on_file_modified("/big.py", big, big + "y")

        store = SnapshotStore.get()
        snaps = store.get_message_snapshots("test-session", "test-large")
        assert len(snaps) == 1
        assert snaps[0].skip_reason == SnapshotSkipReason.FILE_TOO_LARGE

    @pytest.mark.asyncio
    async def test_on_file_viewed_noop(self):
        observer = SnapshotObserver()
        await observer.on_file_viewed("/a.py")
        store = SnapshotStore.get()
        assert store.total_bytes == 0


class TestRevertService:
    @pytest.mark.asyncio
    async def test_revert_modify(self):
        store = SnapshotStore.get()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("modified-content")
            f.flush()
            path = f.name

        try:
            store.record("s1", "m1", FileSnapshot(path, SnapshotOp.MODIFY, "original-content"))
            result = await RevertService.revert_message("s1", "m1")
            assert path in result.reverted_files
            assert Path(path).read_text("utf-8") == "original-content"
        finally:
            if os.path.exists(path):
                os.remove(path)

    @pytest.mark.asyncio
    async def test_revert_create(self):
        store = SnapshotStore.get()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("new file")
            f.flush()
            path = f.name

        store.record("s1", "m1", FileSnapshot(path, SnapshotOp.CREATE, None))
        result = await RevertService.revert_message("s1", "m1")
        assert path in result.reverted_files
        assert not os.path.exists(path)

    @pytest.mark.asyncio
    async def test_revert_no_snapshots(self):
        result = await RevertService.revert_message("none", "none")
        assert result.reverted_files == []
        assert len(result.warnings) > 0

    @pytest.mark.asyncio
    async def test_revert_file_not_found(self):
        store = SnapshotStore.get()
        store.record("s1", "m1", FileSnapshot("/nonexistent.py", SnapshotOp.MODIFY, "old"))
        result = await RevertService.revert_message("s1", "m1")
        assert "/nonexistent.py" in result.skipped_files

    @pytest.mark.asyncio
    async def test_revert_already_matches(self):
        store = SnapshotStore.get()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("original")
            path = f.name

        try:
            store.record("s1", "m1", FileSnapshot(path, SnapshotOp.MODIFY, "original"))
            result = await RevertService.revert_message("s1", "m1")
            assert path in result.reverted_files
        finally:
            os.remove(path)

    @pytest.mark.asyncio
    async def test_revert_file_specific(self):
        store = SnapshotStore.get()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("modified")
            path = f.name

        try:
            store.record("s1", "m1", FileSnapshot(path, SnapshotOp.MODIFY, "original"))
            result = await RevertService.revert_file("s1", "m1", path)
            assert path in result.reverted_files
        finally:
            if os.path.exists(path):
                os.remove(path)

    @pytest.mark.asyncio
    async def test_get_message_changes_skipped(self):
        store = SnapshotStore.get()
        store.record_skipped("s1", "m1", "/big.py", SnapshotOp.MODIFY, SnapshotSkipReason.FILE_TOO_LARGE)
        changes = await RevertService.get_message_changes("s1", "m1")
        assert len(changes) == 1
        assert changes[0].revertible is False
        assert changes[0].skip_reason == "file_too_large"

    @pytest.mark.asyncio
    async def test_revert_message_only_skipped(self):
        store = SnapshotStore.get()
        store.record_skipped("s1", "m1", "/big.py", SnapshotOp.MODIFY, SnapshotSkipReason.FILE_TOO_LARGE)
        result = await RevertService.revert_message("s1", "m1")
        assert result.reverted_files == []
        assert "/big.py" in result.skipped_files

    @pytest.mark.asyncio
    async def test_revert_file_not_revertible(self):
        store = SnapshotStore.get()
        store.record_skipped("s1", "m1", "/big.py", SnapshotOp.MODIFY, SnapshotSkipReason.FILE_TOO_LARGE)
        result = await RevertService.revert_file("s1", "m1", "/big.py")
        assert result.reverted_files == []
        assert "/big.py" in result.skipped_files

    @pytest.mark.asyncio
    async def test_get_message_changes(self):
        store = SnapshotStore.get()
        store.record("s1", "m1", FileSnapshot("/a.py", SnapshotOp.MODIFY, "old"))
        store.record("s1", "m1", FileSnapshot("/b.py", SnapshotOp.CREATE, None))
        changes = await RevertService.get_message_changes("s1", "m1")
        assert len(changes) == 2
        assert changes[0].path == "/a.py"
        assert changes[0].has_original is True
        assert changes[1].path == "/b.py"
        assert changes[1].has_original is False

    @pytest.mark.asyncio
    async def test_dedup_same_file(self):
        """Multiple edits to same file: revert should use first snapshot's content."""
        store = SnapshotStore.get()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("v3")
            path = f.name

        try:
            store.record("s1", "m1", FileSnapshot(path, SnapshotOp.MODIFY, "v1"))
            store.record("s1", "m1", FileSnapshot(path, SnapshotOp.MODIFY, "v2"))
            await RevertService.revert_message("s1", "m1")
            assert Path(path).read_text("utf-8") == "v2"
        finally:
            if os.path.exists(path):
                os.remove(path)

    @pytest.mark.asyncio
    async def test_revert_session(self):
        """Revert all changes in a session."""
        store = SnapshotStore.get()
        paths: list[str] = []

        for i in range(2):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(f"modified-{i}")
                paths.append(f.name)
            store.record("s1", f"m{i}", FileSnapshot(paths[-1], SnapshotOp.MODIFY, f"original-{i}"))

        try:
            result = await RevertService.revert_session("s1")
            assert len(result.reverted_files) == 2
            for i, path in enumerate(paths):
                assert Path(path).read_text("utf-8") == f"original-{i}"
        finally:
            for p in paths:
                if os.path.exists(p):
                    os.remove(p)

    @pytest.mark.asyncio
    async def test_get_session_changes(self):
        store = SnapshotStore.get()
        store.record("s1", "m1", FileSnapshot("/a.py", SnapshotOp.MODIFY, "old"))
        store.record("s1", "m2", FileSnapshot("/b.py", SnapshotOp.CREATE, None))
        changes = await RevertService.get_session_changes("s1")
        assert "m1" in changes
        assert "m2" in changes
        assert len(changes["m1"]) == 1
        assert len(changes["m2"]) == 1

    @pytest.mark.asyncio
    async def test_revert_file_no_snapshot(self):
        result = await RevertService.revert_file("s1", "m1", "/nonexistent.py")
        assert result.reverted_files == []
        assert len(result.warnings) > 0

    @pytest.mark.asyncio
    async def test_revert_modify_no_original(self):
        """MODIFY snapshot with None original_content should be skipped."""
        store = SnapshotStore.get()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("current")
            path = f.name

        try:
            store.record("s1", "m1", FileSnapshot(path, SnapshotOp.MODIFY, None))
            result = await RevertService.revert_message("s1", "m1")
            assert path in result.skipped_files
        finally:
            os.remove(path)


class TestDiskCleanup:
    """Tests for on-disk snapshot cleanup."""

    @pytest.mark.asyncio
    async def test_remove_persisted_message(self, tmp_path):
        store = SnapshotStore.get()
        store.record("s1", "m1", FileSnapshot("/a.py", SnapshotOp.MODIFY, "old"))
        await store.persist_to_disk(str(tmp_path), "s1", "m1")

        snap_file = tmp_path / ".myrm" / "snapshots" / "s1" / "m1.json"
        assert snap_file.is_file()

        await store.remove_persisted_message(str(tmp_path), "s1", "m1")
        assert not snap_file.exists()

    @pytest.mark.asyncio
    async def test_clear_persisted_session(self, tmp_path):
        store = SnapshotStore.get()
        store.record("s1", "m1", FileSnapshot("/a.py", SnapshotOp.MODIFY, "old"))
        store.record("s1", "m2", FileSnapshot("/b.py", SnapshotOp.CREATE, None))
        await store.persist_to_disk(str(tmp_path), "s1", "m1")
        await store.persist_to_disk(str(tmp_path), "s1", "m2")

        session_dir = tmp_path / ".myrm" / "snapshots" / "s1"
        assert session_dir.is_dir()
        assert (session_dir / "m1.json").is_file()
        assert (session_dir / "m2.json").is_file()

        await store.clear_persisted_session(str(tmp_path), "s1")
        assert not session_dir.exists()

    @pytest.mark.asyncio
    async def test_remove_nonexistent_message_no_error(self, tmp_path):
        store = SnapshotStore.get()
        await store.remove_persisted_message(str(tmp_path), "s1", "nonexistent")

    @pytest.mark.asyncio
    async def test_clear_nonexistent_session_no_error(self, tmp_path):
        store = SnapshotStore.get()
        await store.clear_persisted_session(str(tmp_path), "nonexistent")
