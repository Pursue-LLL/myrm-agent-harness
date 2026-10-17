"""Fakes shared by the skill_manage batch runner tests: the writer, the snapshot reader and the commit hook."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from myrm_agent_harness.agent.meta_tools.skills.manage.batch_runner import SkillBatchSnapshot
from myrm_agent_harness.backends.skills.creation_protocols import SkillDeleteResult, SkillSaveResult

STORED = "---\nname: demo\ndescription: stored\n---\nstored body"


class RecordingHook:
    """Commit hook that records every batch it is handed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, SkillBatchSnapshot]]] = []

    async def on_batch_committed(self, batch_id: str, snapshots: dict[str, SkillBatchSnapshot]) -> None:
        self.calls.append((batch_id, snapshots))


class FailingHook:
    """Commit hook whose persistence fails, after the batch already changed the skills."""

    async def on_batch_committed(self, batch_id: str, snapshots: dict[str, SkillBatchSnapshot]) -> None:
        raise RuntimeError("snapshot store is down")


def make_write_backend() -> MagicMock:
    backend = MagicMock()
    backend.save_skill = AsyncMock(
        return_value=SkillSaveResult(success=True, skill_name="demo", skill_id="id1", was_updated=True)
    )
    backend.delete_skill = AsyncMock(return_value=SkillDeleteResult(success=True, skill_name="demo"))
    return backend


def make_reader(content: str | None) -> MagicMock:
    """A snapshot reader whose skill has ``content``, or has no such skill when ``None``."""
    reader = MagicMock()
    if content is None:
        reader.get_skill_content = AsyncMock(side_effect=FileNotFoundError("demo"))
    else:
        reader.get_skill_content = AsyncMock(return_value=content)
    reader.get_skill_resources = AsyncMock(side_effect=FileNotFoundError("missing"))
    return reader
