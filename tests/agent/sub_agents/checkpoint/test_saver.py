"""Tests for SubagentCheckpoint and SubagentCheckpointStorage."""

from __future__ import annotations

import json
import time

import pytest

from myrm_agent_harness.agent.sub_agents.checkpoint.saver import SubagentCheckpoint, SubagentCheckpointStorage


def _make_checkpoint(
    task_id: str = "task-1",
    agent_type: str = "researcher",
    session_id: str = "sess-1",
    progress: float = 0.5,
    resumable: bool = True,
    messages: list[dict[str, object]] | None = None,
    last_tool: str | None = "web_search",
) -> SubagentCheckpoint:
    return SubagentCheckpoint(
        task_id=task_id,
        agent_type=agent_type,
        session_id=session_id,
        timestamp=time.time(),
        messages=messages or [{"role": "user", "content": "hello"}],
        tool_outputs=[{"tool": "search", "result": "ok"}],
        variables={"key": "value"},
        progress=progress,
        last_tool=last_tool,
        resumable=resumable,
    )


# =========================================================================
# SubagentCheckpoint dataclass
# =========================================================================


class TestSubagentCheckpoint:
    def test_to_dict_round_trip(self) -> None:
        cp = _make_checkpoint()
        d = cp.to_dict()
        assert d["task_id"] == "task-1"
        assert d["agent_type"] == "researcher"
        assert d["resumable"] is True

    def test_from_dict(self) -> None:
        original = _make_checkpoint(progress=0.75, last_tool="code_exec")
        d = original.to_dict()
        restored = SubagentCheckpoint.from_dict(d)
        assert restored.task_id == original.task_id
        assert restored.progress == 0.75
        assert restored.last_tool == "code_exec"
        assert restored.messages == original.messages

    def test_default_values(self) -> None:
        cp = SubagentCheckpoint(task_id="t", agent_type="a", session_id="s", timestamp=0.0)
        assert cp.messages == []
        assert cp.tool_outputs == []
        assert cp.variables == {}
        assert cp.progress == 0.0
        assert cp.last_tool is None
        assert cp.resumable is True


# =========================================================================
# SubagentCheckpointStorage
# =========================================================================


class TestSubagentCheckpointStorage:
    @pytest.mark.asyncio
    async def test_save_and_load(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        cp = _make_checkpoint()

        await storage.save(cp)

        loaded = await storage.load("task-1")
        assert loaded is not None
        assert loaded.task_id == "task-1"
        assert loaded.progress == 0.5
        assert loaded.messages == cp.messages

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        assert await storage.load("nonexistent") is None

    @pytest.mark.asyncio
    async def test_delete(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        cp = _make_checkpoint()
        await storage.save(cp)

        await storage.delete("task-1")
        assert await storage.load("task-1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_no_error(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        await storage.delete("nonexistent")

    @pytest.mark.asyncio
    async def test_list_checkpoints(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")

        await storage.save(_make_checkpoint(task_id="a", session_id="s1"))
        await storage.save(_make_checkpoint(task_id="b", session_id="s1"))
        await storage.save(_make_checkpoint(task_id="c", session_id="s2"))

        all_cps = await storage.list_checkpoints()
        assert len(all_cps) == 3

        s1_cps = await storage.list_checkpoints(session_id="s1")
        assert len(s1_cps) == 2
        assert all(cp.session_id == "s1" for cp in s1_cps)

    @pytest.mark.asyncio
    async def test_list_checkpoints_sorted_by_timestamp_desc(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        cp1 = _make_checkpoint(task_id="old")
        cp1.timestamp = 1000.0
        cp2 = _make_checkpoint(task_id="new")
        cp2.timestamp = 2000.0
        await storage.save(cp1)
        await storage.save(cp2)

        result = await storage.list_checkpoints()
        assert result[0].task_id == "new"
        assert result[1].task_id == "old"

    @pytest.mark.asyncio
    async def test_cleanup_old_checkpoints(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")

        old_cp = _make_checkpoint(task_id="old")
        old_cp.timestamp = time.time() - 86400 * 10  # 10 days ago
        await storage.save(old_cp)

        new_cp = _make_checkpoint(task_id="new")
        await storage.save(new_cp)

        deleted = await storage.cleanup_old_checkpoints(ttl_seconds=86400 * 7)
        assert deleted == 1

        remaining = await storage.list_checkpoints()
        assert len(remaining) == 1
        assert remaining[0].task_id == "new"

    @pytest.mark.asyncio
    async def test_cleanup_no_old_checkpoints(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        cp = _make_checkpoint()
        await storage.save(cp)

        deleted = await storage.cleanup_old_checkpoints()
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_metrics_tracking_on_save(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        cp = _make_checkpoint()
        await storage.save(cp)

        if storage.metrics:
            assert storage.metrics.save_count == 1
            assert storage.metrics.save_success_count == 1
            assert storage.metrics.save_total_ms > 0
            assert storage.metrics.messages_extracted_count == 1

    @pytest.mark.asyncio
    async def test_metrics_tracking_on_load(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        cp = _make_checkpoint()
        await storage.save(cp)
        await storage.load("task-1")

        if storage.metrics:
            assert storage.metrics.resume_count == 1
            assert storage.metrics.resume_success_count == 1
            assert storage.metrics.resume_total_ms > 0

    @pytest.mark.asyncio
    async def test_save_failure_tracks_metric(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        cp = _make_checkpoint()

        # Corrupt the path to force IOError
        file_path = storage._storage_path / f"{cp.task_id}.json"
        file_path.mkdir(parents=True)

        with pytest.raises(Exception):
            await storage.save(cp)

        if storage.metrics:
            assert storage.metrics.save_failure_count == 1

    @pytest.mark.asyncio
    async def test_load_corrupt_file_raises(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        file_path = storage._storage_path / "corrupt.json"
        file_path.write_text("not valid json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            await storage.load("corrupt")

    @pytest.mark.asyncio
    async def test_list_skips_corrupt_files(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")

        await storage.save(_make_checkpoint(task_id="good"))

        corrupt = storage._storage_path / "bad.json"
        corrupt.write_text("not json", encoding="utf-8")

        result = await storage.list_checkpoints()
        assert len(result) == 1
        assert result[0].task_id == "good"

    @pytest.mark.asyncio
    async def test_overwrite_checkpoint(self, tmp_path) -> None:
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        cp1 = _make_checkpoint(progress=0.3)
        await storage.save(cp1)

        cp2 = _make_checkpoint(progress=0.9)
        await storage.save(cp2)

        loaded = await storage.load("task-1")
        assert loaded is not None
        assert loaded.progress == 0.9

    @pytest.mark.asyncio
    async def test_save_rejects_non_string_task_id(self, tmp_path) -> None:
        from unittest.mock import MagicMock

        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        cp = _make_checkpoint()
        cp.task_id = MagicMock()  # type: ignore[assignment]

        with pytest.raises(TypeError, match="task_id must be str"):
            await storage.save(cp)

    def test_default_storage_path_uses_myrm_data_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setenv("MYRM_DATA_DIR", str(tmp_path / "data"))
        storage = SubagentCheckpointStorage()
        assert storage._storage_path == tmp_path / "data" / "checkpoints"
