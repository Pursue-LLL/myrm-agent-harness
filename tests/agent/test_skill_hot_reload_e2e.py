"""End-to-End Skill Hot Reload Tests.

Tests that verify skill hot reload works correctly with LocalSkillBackend + SkillWatcher.
This is critical to catch bugs where skill updates are not reflected in subsequent loads.

[INPUT]
- backends.skills.local::LocalSkillBackend (POS: Local skill backend with snapshot support)
- backends.skills.watcher::SkillWatcher (POS: File system watcher for hot reload)
- backends.skills.snapshot::SQLiteSkillSnapshot (POS: Skill snapshot cache)

[OUTPUT]
- test_backend_uses_updated_skill_immediately: E2E test for hot reload at backend level

[POS]
End-to-end tests for skill hot reload. Ensures backend immediately loads updated skills.
"""

import asyncio
from pathlib import Path

import pytest

from myrm_agent_harness.backends.skills.local import LocalSkillBackend
from myrm_agent_harness.backends.skills.watcher import SkillWatcher


@pytest.mark.asyncio
async def test_backend_uses_updated_skill_immediately(tmp_path: Path):
    """
    End-to-end test: Backend immediately loads updated skills after hot reload.

    Scenario:
    1. Create skillA (version 1: "Hello")
    2. Create backend with snapshot support
    3. Load skills (should get version 1)
    4. Externally modify skillA (version 2: "World")
    5. Wait for SkillWatcher to detect change and update snapshot
    6. Backend loads skills again (should get version 2)
    7. Verify backend now loads version 2

    This test verifies that:
    - SkillWatcher detects file changes
    - SQLiteSkillSnapshot is updated
    - LocalSkillBackend reads from updated snapshot
    - No caching breaks hot reload
    """
    # 1. Create skillA (version 1)
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        """---
name: test-skill
description: Test skill version 1
version: "1.0.0"
---

# Test Skill Version 1

This skill returns: Hello
"""
    )

    # 2. Create backend with snapshot + watcher
    backend = LocalSkillBackend(
        skills_dir=tmp_path,
        use_snapshot=True,
    )

    # Initialize snapshot
    from myrm_agent_harness.backends.skills.snapshot import (
        rebuild_local_dir_snapshot,
    )

    await rebuild_local_dir_snapshot(tmp_path)

    # Start watcher for hot reload
    watcher = SkillWatcher(tmp_path)
    watcher.start()

    try:
        # 3. Load skills (version 1)
        skills_v1 = await backend.list_skills()
        assert len(skills_v1) == 1
        assert skills_v1[0].name == "test-skill"
        assert skills_v1[0].version == "1.0.0"
        assert "Test skill version 1" in skills_v1[0].description

        # 4. Externally modify skillA (version 2)
        skill_md.write_text(
            """---
name: test-skill
description: Test skill version 2
version: "2.0.0"
---

# Test Skill Version 2

This skill returns: World
"""
        )

        # 5. Wait for SkillWatcher to detect change and update snapshot
        # Debounce window is 0.5s, give it 1.5s to be safe
        await asyncio.sleep(1.5)

        # 6. Backend loads skills again (should get version 2)
        # CRITICAL: This verifies no caching breaks hot reload
        skills_v2 = await backend.list_skills()

        # 7. Verify backend now loads version 2
        assert len(skills_v2) == 1
        assert skills_v2[0].name == "test-skill"
        assert skills_v2[0].version == "2.0.0", (
            f"Hot reload failed! Backend still loads version {skills_v2[0].version}, "
            f"expected 2.0.0. Snapshot may not have been updated."
        )
        assert (
            "Test skill version 2" in skills_v2[0].description
        ), "Hot reload failed! Backend still loads old description"

    finally:
        # Cleanup
        watcher.stop()


@pytest.mark.asyncio
async def test_backend_detects_new_skill(tmp_path: Path):
    """Test that backend can detect newly created skills via hot reload."""
    # 1. Start with empty directory
    backend = LocalSkillBackend(
        skills_dir=tmp_path,
        use_snapshot=True,
    )

    from myrm_agent_harness.backends.skills.snapshot import (
        rebuild_local_dir_snapshot,
    )

    await rebuild_local_dir_snapshot(tmp_path)

    watcher = SkillWatcher(tmp_path)
    watcher.start()

    try:
        # 2. Verify no skills initially
        skills_initial = await backend.list_skills()
        assert len(skills_initial) == 0

        # 3. Create a new skill
        skill_dir = tmp_path / "new-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            """---
name: new-skill
description: Newly created skill
version: "1.0.0"
---

# New Skill

This is a newly created skill.
"""
        )

        # 4. Wait for watcher
        await asyncio.sleep(1.5)

        # 5. Verify backend can see the new skill
        skills_after = await backend.list_skills()
        assert len(skills_after) == 1
        assert skills_after[0].name == "new-skill"

    finally:
        watcher.stop()


@pytest.mark.asyncio
async def test_backend_detects_deleted_skill(tmp_path: Path):
    """Test that backend can detect deleted skills via hot reload."""
    # 1. Create a skill
    skill_dir = tmp_path / "temp-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        """---
name: temp-skill
description: Temporary skill
version: "1.0.0"
---

# Temp Skill
"""
    )

    backend = LocalSkillBackend(
        skills_dir=tmp_path,
        use_snapshot=True,
    )

    from myrm_agent_harness.backends.skills.snapshot import (
        rebuild_local_dir_snapshot,
    )

    await rebuild_local_dir_snapshot(tmp_path)

    watcher = SkillWatcher(tmp_path)
    watcher.start()

    try:
        # 2. Verify skill exists
        skills_initial = await backend.list_skills()
        assert len(skills_initial) == 1
        assert skills_initial[0].name == "temp-skill"

        # 3. Delete the skill
        skill_md.unlink()
        skill_dir.rmdir()

        # 4. Wait for watcher
        await asyncio.sleep(1.5)

        # 5. Verify backend no longer sees the deleted skill
        skills_after = await backend.list_skills()
        assert len(skills_after) == 0

    finally:
        watcher.stop()
