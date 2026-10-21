"""Tests for atomic skill_manage batch runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.skills.manage.batch_runner import run_skill_manage_batch
from myrm_agent_harness.backends.skills.creation_protocols import SkillResourceWriteResult, SkillSaveResult


@pytest.mark.asyncio
async def test_batch_aborts_and_rolls_back_on_second_op_failure() -> None:
    write_backend = MagicMock()
    write_backend.save_skill = AsyncMock(
        return_value=SkillSaveResult(success=True, skill_name="demo", skill_id="id1")
    )
    write_backend.write_resource = AsyncMock(
        side_effect=[
            SkillResourceWriteResult(success=True, skill_name="demo", resource_path="scripts/a.py"),
            SkillResourceWriteResult(success=False, skill_name="demo", resource_path="scripts/b.py", error="blocked"),
        ]
    )
    write_backend.delete_resource = AsyncMock(
        return_value=SkillResourceWriteResult(success=True, skill_name="demo", resource_path="scripts/a.py")
    )

    skill_backend = MagicMock()
    skill_backend.get_skill_content = AsyncMock(return_value="---\nname: demo\n---\nbody")
    skill_backend.get_skill_resources = AsyncMock(return_value=b"old")

    result = await run_skill_manage_batch(
        write_backend=write_backend,
        skill_backend=skill_backend,
        similarity_checker=None,
        operations=[
            {"action": "write_file", "name": "demo", "file_path": "scripts/a.py", "content": "new"},
            {"action": "write_file", "name": "demo", "file_path": "scripts/b.py", "content": "bad"},
        ],
    )

    assert "batch aborted" in result.lower()
    write_backend.save_skill.assert_called()
