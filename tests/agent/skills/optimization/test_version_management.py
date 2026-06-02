"""Tests for Skill Version Management"""

import pytest

from myrm_agent_harness.agent.skills.optimization import InMemoryStorage, SkillQualityScore, StorageError


@pytest.fixture
def storage():
    return InMemoryStorage(max_records=100, ttl_seconds=None)


@pytest.fixture
def quality_score():
    return SkillQualityScore(
        success_rate=0.95, token_efficiency=0.85, execution_time=0.90, user_satisfaction=0.88, call_frequency=0.75
    )


@pytest.mark.asyncio
async def test_save_and_get_version(storage, quality_score):
    """Test saving and retrieving a skill version"""
    version = await storage.save_skill_version(
        skill_id="test-skill",
        version=1,
        content="# Test Skill V1\nThis is version 1",
        quality_score=quality_score,
        created_by="llm",
    )

    assert version.skill_id == "test-skill"
    assert version.version == 1
    assert version.content == "# Test Skill V1\nThis is version 1"
    assert version.quality_score == quality_score
    assert version.created_by == "llm"
    assert version.is_active is False

    # Retrieve
    retrieved = await storage.get_skill_version("test-skill", 1)
    assert retrieved is not None
    assert retrieved.skill_id == version.skill_id
    assert retrieved.version == version.version


@pytest.mark.asyncio
async def test_list_versions(storage, quality_score):
    """Test listing skill versions"""
    # Save multiple versions
    await storage.save_skill_version(skill_id="test-skill", version=1, content="Version 1", quality_score=quality_score)
    await storage.save_skill_version(skill_id="test-skill", version=2, content="Version 2", quality_score=quality_score)
    await storage.save_skill_version(skill_id="test-skill", version=3, content="Version 3", quality_score=quality_score)

    # List versions
    versions = await storage.list_skill_versions("test-skill")
    assert len(versions) == 3
    # Should be sorted by version descending
    assert versions[0].version == 3
    assert versions[1].version == 2
    assert versions[2].version == 1


@pytest.mark.asyncio
async def test_activate_version(storage, quality_score):
    """Test activating a version (rollback)"""
    # Save versions
    await storage.save_skill_version(skill_id="test-skill", version=1, content="Version 1", quality_score=quality_score)
    await storage.save_skill_version(skill_id="test-skill", version=2, content="Version 2", quality_score=quality_score)

    # Activate v2
    activated = await storage.activate_version("test-skill", 2)
    assert activated.is_active is True
    assert activated.version == 2

    # Get active version
    active = await storage.get_active_version("test-skill")
    assert active is not None
    assert active.version == 2
    assert active.is_active is True

    # Rollback to v1
    activated = await storage.activate_version("test-skill", 1)
    assert activated.is_active is True
    assert activated.version == 1

    # Verify v2 is no longer active
    v2_current = await storage.get_skill_version("test-skill", 2)
    assert v2_current.is_active is False


@pytest.mark.asyncio
async def test_delete_old_versions(storage, quality_score):
    """Test deleting old versions"""
    # Save 15 versions
    for i in range(1, 16):
        await storage.save_skill_version(
            skill_id="test-skill", version=i, content=f"Version {i}", quality_score=quality_score
        )

    # Activate version 5
    await storage.activate_version("test-skill", 5)

    # Delete old versions, keeping latest 10
    deleted = await storage.delete_skill_versions("test-skill", keep_latest=10)

    # Should delete 5 versions (versions 1-4 and 6, keeping 5 as active and 7-15)
    # Actually, keeping latest 10 means keeping versions 6-15, plus active version 5
    # So should delete versions 1-4
    assert deleted == 4

    # Verify remaining versions
    versions = await storage.list_skill_versions("test-skill")
    assert len(versions) == 11  # 10 latest + 1 active

    # Verify active version is kept
    active = await storage.get_active_version("test-skill")
    assert active is not None
    assert active.version == 5


@pytest.mark.asyncio
async def test_version_not_found(storage):
    """Test error handling for non-existent versions"""
    # Get non-existent version
    result = await storage.get_skill_version("nonexistent", 1)
    assert result is None

    # Activate non-existent version
    with pytest.raises(StorageError):
        await storage.activate_version("nonexistent", 1)


@pytest.mark.asyncio
async def test_get_active_version_none(storage):
    """Test getting active version when none is set"""
    # Save a version but don't activate
    await storage.save_skill_version(skill_id="test-skill", version=1, content="Version 1")

    # Should return None
    active = await storage.get_active_version("test-skill")
    assert active is None
