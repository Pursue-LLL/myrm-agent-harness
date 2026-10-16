"""Where the skill_manage batch runner snapshots from, and that a delete leaves no undo record."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.skills.manage.batch_runner import (
    SKILL_BATCH_JSON_PREFIX,
    SkillBatchSnapshot,
    run_skill_manage_batch,
)
from myrm_agent_harness.backends.skills.creation_protocols import SkillDeleteResult, SkillSaveResult

STORED = "---\nname: demo\ndescription: stored\n---\nstored body"


class _RecordingHook:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, SkillBatchSnapshot]]] = []

    async def on_batch_committed(self, batch_id: str, snapshots: dict[str, SkillBatchSnapshot]) -> None:
        self.calls.append((batch_id, snapshots))


def _write_backend() -> MagicMock:
    backend = MagicMock()
    backend.save_skill = AsyncMock(
        return_value=SkillSaveResult(success=True, skill_name="demo", skill_id="id1", was_updated=True)
    )
    backend.delete_skill = AsyncMock(return_value=SkillDeleteResult(success=True, skill_name="demo"))
    return backend


def _reader(content: str | None) -> MagicMock:
    reader = MagicMock()
    if content is None:
        reader.get_skill_content = AsyncMock(side_effect=FileNotFoundError("demo"))
    else:
        reader.get_skill_content = AsyncMock(return_value=content)
    reader.get_skill_resources = AsyncMock(side_effect=FileNotFoundError("missing"))
    return reader


_SAVE: list[dict[str, object]] = [
    {"action": "save", "name": "demo", "content": "---\nname: demo\ndescription: new\n---\nnew body"}
]
_PATCH: list[dict[str, object]] = [
    {"action": "patch", "name": "demo", "old_content": "stored body", "new_content": "patched body"}
]
PATCHED = STORED.replace("stored body", "patched body")


@pytest.mark.asyncio
async def test_snapshot_is_read_through_the_snapshot_reader_not_the_turn_backend() -> None:
    hook = _RecordingHook()
    turn_backend = _reader(None)

    await run_skill_manage_batch(
        write_backend=_write_backend(),
        skill_backend=turn_backend,
        similarity_checker=None,
        operations=_SAVE,
        batch_committed_hook=hook,
        snapshot_reader=_reader(STORED),
    )

    snapshot = hook.calls[0][1]["demo"]
    assert snapshot.existed_before_batch is True
    assert snapshot.skill_md == STORED
    turn_backend.get_skill_content.assert_not_called()


@pytest.mark.asyncio
async def test_snapshot_falls_back_to_the_skill_backend_without_a_reader() -> None:
    hook = _RecordingHook()

    await run_skill_manage_batch(
        write_backend=_write_backend(),
        skill_backend=_reader(STORED),
        similarity_checker=None,
        operations=_SAVE,
        batch_committed_hook=hook,
    )

    assert hook.calls[0][1]["demo"].skill_md == STORED


@pytest.mark.asyncio
async def test_a_skill_the_reader_cannot_find_is_recorded_as_new() -> None:
    hook = _RecordingHook()

    await run_skill_manage_batch(
        write_backend=_write_backend(),
        skill_backend=None,
        similarity_checker=None,
        operations=_SAVE,
        batch_committed_hook=hook,
        snapshot_reader=_reader(None),
    )

    snapshot = hook.calls[0][1]["demo"]
    assert snapshot.existed_before_batch is False
    assert snapshot.skill_md is None


@pytest.mark.asyncio
async def test_a_committed_batch_reports_its_id_and_the_undo_hint() -> None:
    hook = _RecordingHook()

    output = await run_skill_manage_batch(
        write_backend=_write_backend(),
        skill_backend=None,
        similarity_checker=None,
        operations=_SAVE,
        batch_committed_hook=hook,
        snapshot_reader=_reader(STORED),
        locale="en",
    )

    batch_id = hook.calls[0][0]
    assert f"batch_id={batch_id}" in output
    assert f"{SKILL_BATCH_JSON_PREFIX}" in output
    assert "Undo skill changes" in output


@pytest.mark.asyncio
@pytest.mark.parametrize(("locale", "note"), [("en", "no undo for it"), ("zh-CN", "无法撤销")])
async def test_a_delete_is_final_and_leaves_no_undo_record(locale: str, note: str) -> None:
    hook = _RecordingHook()

    output = await run_skill_manage_batch(
        write_backend=_write_backend(),
        skill_backend=None,
        similarity_checker=None,
        operations=[{"action": "delete", "name": "demo"}],
        batch_committed_hook=hook,
        snapshot_reader=_reader(STORED),
        locale=locale,
    )

    assert hook.calls == []
    assert "deleted successfully" in output
    assert note in output
    # The server turns these into an Undo entry for a batch that has no snapshot.
    assert "Batch applied successfully" not in output
    assert "batch_id=" not in output
    assert SKILL_BATCH_JSON_PREFIX not in output


@pytest.mark.asyncio
async def test_a_patch_edits_a_skill_the_turn_backend_cannot_see_through_the_writers_storage() -> None:
    write_backend = _write_backend()

    output = await run_skill_manage_batch(
        write_backend=write_backend,
        skill_backend=_reader(None),
        similarity_checker=None,
        operations=_PATCH,
        snapshot_reader=_reader(STORED),
    )

    assert "patched successfully" in output
    assert write_backend.save_skill.await_args.kwargs["content"] == PATCHED


@pytest.mark.asyncio
async def test_a_patch_edits_what_the_writer_will_overwrite_not_a_stale_turn_view() -> None:
    write_backend = _write_backend()
    stale_turn_backend = _reader(STORED.replace("stored body", "older body"))

    output = await run_skill_manage_batch(
        write_backend=write_backend,
        skill_backend=stale_turn_backend,
        similarity_checker=None,
        operations=_PATCH,
        snapshot_reader=_reader(STORED),
    )

    assert "patched successfully" in output
    assert write_backend.save_skill.await_args.kwargs["content"] == PATCHED
    stale_turn_backend.get_skill_content.assert_not_called()


@pytest.mark.asyncio
async def test_a_patch_falls_back_to_the_turn_backend_for_a_skill_outside_the_writers_storage() -> None:
    write_backend = _write_backend()

    output = await run_skill_manage_batch(
        write_backend=write_backend,
        skill_backend=_reader(STORED),
        similarity_checker=None,
        operations=_PATCH,
        snapshot_reader=_reader(None),
    )

    assert "patched successfully" in output
    assert write_backend.save_skill.await_args.kwargs["content"] == PATCHED
