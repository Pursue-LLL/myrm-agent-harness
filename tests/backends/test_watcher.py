import asyncio

import pytest

from myrm_agent_harness.backends.skills.snapshot import SQLiteSkillSnapshot
from myrm_agent_harness.backends.skills.watcher import SkillWatcher


@pytest.fixture
def temp_watch_dir(tmp_path):
    """Create a temporary directory for watching."""
    return tmp_path


@pytest.mark.asyncio
async def test_watcher_initialization(temp_watch_dir):
    """Test SkillWatcher initialization."""
    watcher = SkillWatcher(temp_watch_dir)
    assert watcher.watch_dir == temp_watch_dir.resolve()
    assert watcher.snapshot_path == temp_watch_dir.resolve() / ".skills_snapshot.sqlite"
    assert watcher.observer is None


@pytest.mark.asyncio
async def test_watcher_start_stop(temp_watch_dir):
    """Test SkillWatcher start and stop."""
    watcher = SkillWatcher(temp_watch_dir)

    # Start watcher
    watcher.start()
    assert watcher.observer is not None
    assert watcher.observer.is_alive()

    # Stop watcher
    watcher.stop()
    assert watcher.observer is None


@pytest.mark.asyncio
async def test_watcher_detects_new_skill(temp_watch_dir):
    """Test that watcher detects new skill creation."""
    snapshot_path = temp_watch_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)

    watcher = SkillWatcher(temp_watch_dir, snapshot_path=snapshot_path)
    watcher.start()

    # Give watcher time to initialize
    await asyncio.sleep(0.1)

    # Create a new skill
    skill1 = temp_watch_dir / "skill1"
    skill1.mkdir()
    (skill1 / "SKILL.md").write_text(
        """---
description: test skill 1
version: 1.0.0
---
Test content
""",
        encoding="utf-8",
    )

    # Wait for watcher to process the event
    await asyncio.sleep(1.0)

    # Check that skill was added to snapshot
    skills = snapshot.read_all()
    watcher.stop()

    assert len(skills) == 1
    assert skills[0].name == "skill1"
    assert skills[0].description == "test skill 1"


@pytest.mark.asyncio
async def test_watcher_detects_skill_modification(temp_watch_dir):
    """Test that watcher detects skill modification."""
    # Create initial skill
    skill1 = temp_watch_dir / "skill1"
    skill1.mkdir()
    (skill1 / "SKILL.md").write_text(
        """---
description: test skill 1
version: 1.0.0
---
Test content
""",
        encoding="utf-8",
    )

    snapshot_path = temp_watch_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)
    snapshot.sync_all(temp_watch_dir, max_depth=1)

    watcher = SkillWatcher(temp_watch_dir, snapshot_path=snapshot_path)
    watcher.start()

    # Give watcher time to initialize
    await asyncio.sleep(0.1)

    # Modify the skill
    (skill1 / "SKILL.md").write_text(
        """---
description: test skill 1 updated
version: 1.0.1
---
Test content updated
""",
        encoding="utf-8",
    )

    # Wait for watcher to process the event
    await asyncio.sleep(1.0)

    # Check that skill was updated in snapshot
    skills = snapshot.read_all()
    watcher.stop()

    assert len(skills) == 1
    assert skills[0].name == "skill1"
    assert skills[0].description == "test skill 1 updated"
    assert skills[0].version == "1.0.1"


@pytest.mark.asyncio
async def test_watcher_detects_skill_deletion(temp_watch_dir):
    """Test that watcher detects skill deletion."""
    # Create initial skill
    skill1 = temp_watch_dir / "skill1"
    skill1.mkdir()
    (skill1 / "SKILL.md").write_text(
        """---
description: test skill 1
version: 1.0.0
---
Test content
""",
        encoding="utf-8",
    )

    snapshot_path = temp_watch_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)
    snapshot.sync_all(temp_watch_dir, max_depth=1)

    watcher = SkillWatcher(temp_watch_dir, snapshot_path=snapshot_path)
    watcher.start()

    # Give watcher time to initialize
    await asyncio.sleep(0.1)

    # Delete the skill directory
    import shutil

    shutil.rmtree(skill1)

    # Wait for watcher to process the event
    await asyncio.sleep(1.0)

    # Check that skill was removed from snapshot
    skills = snapshot.read_all()
    watcher.stop()

    assert len(skills) == 0


@pytest.mark.asyncio
async def test_watcher_ignores_hidden_files(temp_watch_dir):
    """Test that watcher ignores hidden files and directories."""
    snapshot_path = temp_watch_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)

    watcher = SkillWatcher(temp_watch_dir, snapshot_path=snapshot_path)
    watcher.start()

    # Give watcher time to initialize
    await asyncio.sleep(0.1)

    # Create a hidden directory (should be ignored)
    hidden_skill = temp_watch_dir / ".hidden_skill"
    hidden_skill.mkdir()
    (hidden_skill / "SKILL.md").write_text(
        """---
description: hidden skill
version: 1.0.0
---
Test content
""",
        encoding="utf-8",
    )

    # Wait for potential processing
    await asyncio.sleep(1.0)

    # Check that hidden skill was NOT added
    skills = snapshot.read_all()
    watcher.stop()

    assert len(skills) == 0


@pytest.mark.asyncio
async def test_watcher_debouncing(temp_watch_dir):
    """Test that watcher debouncing works - multiple rapid changes trigger single update."""
    skill1 = temp_watch_dir / "skill1"
    skill1.mkdir()
    skill_md = skill1 / "SKILL.md"

    # Create initial skill
    skill_md.write_text(
        """---
description: test skill v1
version: 1.0.0
---
Initial content
""",
        encoding="utf-8",
    )

    snapshot_path = temp_watch_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)
    snapshot.sync_all(temp_watch_dir, max_depth=1)

    watcher = SkillWatcher(temp_watch_dir, snapshot_path=snapshot_path)
    watcher.start()

    # Give watcher time to initialize
    await asyncio.sleep(0.1)

    # Perform rapid consecutive modifications (simulating editor auto-save)
    for i in range(5):
        skill_md.write_text(
            f"""---
description: test skill v{i+2}
version: 1.0.{i+1}
---
Content iteration {i+1}
""",
            encoding="utf-8",
        )
        await asyncio.sleep(0.05)  # 50ms between modifications

    # Wait for debouncing to complete (default 0.5s)
    await asyncio.sleep(0.7)

    # Check that final version is in snapshot
    skills = snapshot.read_all()
    watcher.stop()

    assert len(skills) == 1
    assert skills[0].name == "skill1"
    # Should have the last version
    assert skills[0].description == "test skill v6"
    assert skills[0].version == "1.0.5"
