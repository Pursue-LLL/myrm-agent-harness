from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.context_management.tracking.task_metrics_registry import (
    clear_task_metrics,
    create_task_metrics,
)
from myrm_agent_harness.runtime.context import archive_restore_action as archive_restore_action_module
from myrm_agent_harness.runtime.context.archive_restore_action import (
    ArchiveRestoreActionError,
    materialize_archive_restore_action,
)


@pytest.mark.asyncio
async def test_materialize_archive_restore_action_reads_valid_range(tmp_path):
    archive_path = tmp_path / ".context" / "chat-1" / "compacted" / "result.txt"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    restored = await materialize_archive_restore_action(
        workspace_dir=str(tmp_path),
        chat_id="chat-1",
        restore_arg=".context/chat-1/compacted/result.txt:2-3",
    )

    assert restored.archive_path == ".context/chat-1/compacted/result.txt"
    assert restored.content == "beta\ngamma"
    assert restored.start_line == 2
    assert restored.end_line == 3
    assert "<archive_restore" in restored.render_xml()
    result = restored.to_result().to_dict()
    assert result["type"] == "archive_restore_result"
    assert result["restore_arg"] == ".context/chat-1/compacted/result.txt:2-3"
    assert result["restored_line_count"] == 2
    assert result["restored_bytes"] == 10


@pytest.mark.asyncio
async def test_materialize_archive_restore_action_records_result_metrics(tmp_path):
    clear_task_metrics("chat-1")
    metrics = create_task_metrics("chat-1")
    archive_path = tmp_path / ".context" / "chat-1" / "compacted" / "result.txt"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    try:
        await materialize_archive_restore_action(
            workspace_dir=str(tmp_path),
            chat_id="chat-1",
            restore_arg=".context/chat-1/compacted/result.txt:2-3",
        )

        assert metrics.archive_restore_result_count == 1
        assert metrics.archive_restore_result_lines == 2
        assert metrics.archive_restore_result_bytes == 10
        assert metrics.to_dict()["archive_restore_result_events"] == [
            metrics.archive_restore_result_events[0].to_dict()
        ]
    finally:
        clear_task_metrics("chat-1")


@pytest.mark.asyncio
async def test_materialize_archive_restore_action_rejects_cross_session(tmp_path):
    archive_path = tmp_path / ".context" / "chat-2" / "compacted" / "result.txt"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text("alpha\n", encoding="utf-8")

    with pytest.raises(ArchiveRestoreActionError, match="current session"):
        await materialize_archive_restore_action(
            workspace_dir=str(tmp_path),
            chat_id="chat-1",
            restore_arg=".context/chat-2/compacted/result.txt:1-1",
        )


@pytest.mark.asyncio
async def test_materialize_archive_restore_action_streams_requested_range(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    archive_path = tmp_path / ".context" / "chat-1" / "compacted" / "large.txt"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text("\n".join(f"line-{index}" for index in range(1, 1001)), encoding="utf-8")

    def fail_read_text(self: Path, *args: object, **kwargs: object) -> str:
        raise AssertionError("archive restore range reads must not load the whole file")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    restored = await materialize_archive_restore_action(
        workspace_dir=str(tmp_path),
        chat_id="chat-1",
        restore_arg=".context/chat-1/compacted/large.txt:500-502",
    )

    assert restored.content == "line-500\nline-501\nline-502"


@pytest.mark.asyncio
async def test_materialize_archive_restore_action_reuses_sparse_line_index(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    archive_path = tmp_path / ".context" / "chat-1" / "compacted" / "late.txt"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text("\n".join(f"line-{index}" for index in range(1, 5001)), encoding="utf-8")

    restored = await materialize_archive_restore_action(
        workspace_dir=str(tmp_path),
        chat_id="chat-1",
        restore_arg=".context/chat-1/compacted/late.txt:4500-4502",
    )

    assert restored.content == "line-4500\nline-4501\nline-4502"
    assert archive_path.with_name("late.txt.line_index.json").is_file()

    def fail_rebuild(*args: object, **kwargs: object) -> None:
        raise AssertionError("existing archive line index should be reused")

    monkeypatch.setattr(archive_restore_action_module, "_build_line_offset_index", fail_rebuild)

    restored_again = await materialize_archive_restore_action(
        workspace_dir=str(tmp_path),
        chat_id="chat-1",
        restore_arg=".context/chat-1/compacted/late.txt:4998-5000",
    )

    assert restored_again.content == "line-4998\nline-4999\nline-5000"
