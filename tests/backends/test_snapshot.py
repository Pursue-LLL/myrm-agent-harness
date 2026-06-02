from pathlib import Path

import pytest

from myrm_agent_harness.backends.skills.local import (
    LocalSkillBackend,
    scan_workspace_skills,
)
from myrm_agent_harness.backends.skills.snapshot import (
    SQLiteSkillSnapshot,
    rebuild_local_dir_snapshot,
    rebuild_workspace_snapshot,
)


@pytest.fixture
def temp_skills_dir(tmp_path):
    skill1 = tmp_path / "skill1"
    skill1.mkdir()
    (skill1 / "SKILL.md").write_text(
        """---
description: test 1
version: 1.0.0
---
Content 1
""",
        encoding="utf-8",
    )

    skill2 = tmp_path / "skill2"
    skill2.mkdir()
    (skill2 / "SKILL.md").write_text(
        """---
description: test 2
version: 2.0.0
---
Content 2
""",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.asyncio
async def test_snapshot_lifecycle(temp_skills_dir):
    # Test building local snapshot
    await rebuild_local_dir_snapshot(temp_skills_dir)
    snapshot_path = temp_skills_dir / ".skills_snapshot.sqlite"
    assert snapshot_path.exists()

    snapshot = SQLiteSkillSnapshot(snapshot_path)
    skills = snapshot.read_all()
    assert len(skills) == 2
    assert any(s.name == "skill1" for s in skills)

    # Test reading via LocalSkillBackend
    backend = LocalSkillBackend(temp_skills_dir, use_snapshot=True)
    loaded_skills = await backend.list_skills()
    assert len(loaded_skills) == 2

    # Test workspace snapshot
    rebuild_workspace_snapshot(temp_skills_dir)
    workspace_snapshot_path = temp_skills_dir / ".skills_snapshot.sqlite"
    assert workspace_snapshot_path.exists()

    workspace_skills = scan_workspace_skills(temp_skills_dir, use_snapshot=True)
    assert len(workspace_skills) == 2

    # Test clear and delete
    snapshot.delete_skill("skill1")
    assert len(snapshot.read_all()) == 1

    snapshot.clear()
    assert len(snapshot.read_all()) == 0


@pytest.mark.asyncio
async def test_snapshot_invalid_paths():
    # Test invalid dir
    invalid_path = Path("/invalid/path/that/does/not/exist/12345")
    await rebuild_local_dir_snapshot(invalid_path)
    rebuild_workspace_snapshot(invalid_path)

    snapshot = SQLiteSkillSnapshot(invalid_path / ".skills_snapshot.sqlite")
    assert len(snapshot.read_all()) == 0
    snapshot.update_snapshot([])
    snapshot.delete_skill("invalid")
    snapshot.clear()


@pytest.mark.asyncio
async def test_snapshot_delete_from_path(temp_skills_dir):
    # Build snapshot
    await rebuild_local_dir_snapshot(temp_skills_dir)
    snapshot_path = temp_skills_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)

    # Test delete_from_path
    skill1_path = temp_skills_dir / "skill1" / "SKILL.md"
    assert snapshot.delete_from_path(skill1_path)
    skills = snapshot.read_all()
    assert len(skills) == 1
    assert skills[0].name == "skill2"

    # Test delete non-existent skill
    assert not snapshot.delete_from_path(temp_skills_dir / "nonexistent" / "SKILL.md")


@pytest.mark.asyncio
async def test_snapshot_upsert_from_path(temp_skills_dir):
    # Test upsert_from_path
    snapshot_path = temp_skills_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)

    # Test adding a new skill
    skill1_path = temp_skills_dir / "skill1" / "SKILL.md"
    assert snapshot.upsert_from_path(skill1_path, workspace_root=temp_skills_dir)
    skills = snapshot.read_all()
    assert len(skills) == 1
    assert skills[0].name == "skill1"

    # Test updating an existing skill
    (temp_skills_dir / "skill1" / "SKILL.md").write_text(
        """---
description: test 1 updated
version: 1.0.1
---
Content 1 updated
""",
        encoding="utf-8",
    )
    assert snapshot.upsert_from_path(skill1_path, workspace_root=temp_skills_dir)
    skills = snapshot.read_all()
    assert len(skills) == 1
    assert skills[0].description == "test 1 updated"

    # Test invalid path
    assert not snapshot.upsert_from_path(temp_skills_dir / "invalid.txt")
    assert not snapshot.upsert_from_path(temp_skills_dir / "nonexistent" / "SKILL.md")


@pytest.mark.asyncio
async def test_snapshot_sync_all_with_deletions(temp_skills_dir):
    # Build initial snapshot
    snapshot_path = temp_skills_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)
    snapshot.sync_all(temp_skills_dir, max_depth=1)

    skills = snapshot.read_all()
    assert len(skills) == 2

    # Delete a skill directory
    import shutil

    shutil.rmtree(temp_skills_dir / "skill1")

    # Sync again - should detect deletion
    snapshot.sync_all(temp_skills_dir, max_depth=1)
    skills = snapshot.read_all()
    assert len(skills) == 1
    assert skills[0].name == "skill2"

    # Add a new skill
    skill3 = temp_skills_dir / "skill3"
    skill3.mkdir()
    (skill3 / "SKILL.md").write_text(
        """---
description: test 3
version: 3.0.0
---
Content 3
""",
        encoding="utf-8",
    )

    # Sync again - should detect new skill
    snapshot.sync_all(temp_skills_dir, max_depth=1)
    skills = snapshot.read_all()
    assert len(skills) == 2
    skill_names = {s.name for s in skills}
    assert skill_names == {"skill2", "skill3"}


@pytest.mark.asyncio
async def test_snapshot_update_snapshot(temp_skills_dir):
    # Test update_snapshot method (batch update)
    from myrm_agent_harness.backends.skills.local import scan_workspace_skills

    snapshot_path = temp_skills_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)

    # Scan and get skill metadata
    skills = scan_workspace_skills(temp_skills_dir, use_snapshot=False)

    # Update snapshot with all skills
    snapshot.update_snapshot(skills)

    # Verify all skills are in snapshot
    snapshot_skills = snapshot.read_all()
    assert len(snapshot_skills) == 2
    snapshot_names = {s.name for s in snapshot_skills}
    assert snapshot_names == {"skill1", "skill2"}
