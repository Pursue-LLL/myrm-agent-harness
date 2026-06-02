"""Unit tests for SkillAgent desired_skill_ids filtering.

Verifies:
1. desired_skill_ids=None → loads all skills
2. desired_skill_ids=[] → loads 0 skills
3. desired_skill_ids=['skill1'] → loads only skill1
4. desired_skill_ids with invalid IDs → gracefully ignores
5. Backend without load_skills() → fallback to list_skills()
"""

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillTrust


class MockSkillBackend:
    """Mock skill backend with both list_skills() and load_skills()."""

    def __init__(self, skills: list[SkillMetadata]):
        self._skills = skills

    async def list_skills(self) -> list[SkillMetadata]:
        return list(self._skills)

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        id_set = set(skill_ids)
        return [s for s in self._skills if s.name in id_set or (s.storage_skill_id and s.storage_skill_id in id_set)]


class MockSkillBackendNoLoadSupport:
    """Mock skill backend without load_skills() support."""

    def __init__(self, skills: list[SkillMetadata]):
        self._skills = skills

    async def list_skills(self) -> list[SkillMetadata]:
        return list(self._skills)


@pytest.fixture
def sample_skills() -> list[SkillMetadata]:
    """Sample skills for testing."""
    return [
        SkillMetadata(name="skill1", description="Skill 1", trust=SkillTrust.INSTALLED),
        SkillMetadata(name="skill2", description="Skill 2", trust=SkillTrust.INSTALLED),
        SkillMetadata(name="skill3", description="Skill 3", trust=SkillTrust.INSTALLED),
    ]


@pytest.mark.asyncio
async def test_desired_skill_ids_none_loads_all(sample_skills):
    """Test desired_skill_ids=None loads all skills."""
    from myrm_agent_harness.agent.skill_agent import SkillAgent

    llm = MagicMock()
    backend = MockSkillBackend(sample_skills)

    agent = SkillAgent(
        llm=llm,
        skill_backend=backend,
        desired_skill_ids=None,  # Should load all
    )

    skills = await agent._get_cached_skills()
    assert len(skills) == 3
    assert {s.name for s in skills} == {"skill1", "skill2", "skill3"}


@pytest.mark.asyncio
async def test_desired_skill_ids_empty_loads_zero(sample_skills):
    """Test desired_skill_ids=[] loads 0 skills."""
    from myrm_agent_harness.agent.skill_agent import SkillAgent

    llm = MagicMock()
    backend = MockSkillBackend(sample_skills)

    agent = SkillAgent(
        llm=llm,
        skill_backend=backend,
        desired_skill_ids=[],  # Should load 0 skills
    )

    skills = await agent._get_cached_skills()
    assert len(skills) == 0


@pytest.mark.asyncio
async def test_desired_skill_ids_filters_correctly(sample_skills):
    """Test desired_skill_ids=['skill1', 'skill3'] loads only those 2."""
    from myrm_agent_harness.agent.skill_agent import SkillAgent

    llm = MagicMock()
    backend = MockSkillBackend(sample_skills)

    agent = SkillAgent(llm=llm, skill_backend=backend, desired_skill_ids=["skill1", "skill3"])

    skills = await agent._get_cached_skills()
    assert len(skills) == 2
    assert {s.name for s in skills} == {"skill1", "skill3"}


@pytest.mark.asyncio
async def test_desired_skill_ids_with_invalid_ids(sample_skills):
    """Test desired_skill_ids with invalid IDs gracefully ignores them."""
    from myrm_agent_harness.agent.skill_agent import SkillAgent

    llm = MagicMock()
    backend = MockSkillBackend(sample_skills)

    agent = SkillAgent(llm=llm, skill_backend=backend, desired_skill_ids=["skill1", "invalid_id", "skill2"])

    skills = await agent._get_cached_skills()
    assert len(skills) == 2  # Only valid IDs loaded
    assert {s.name for s in skills} == {"skill1", "skill2"}


@pytest.mark.asyncio
async def test_fallback_to_list_skills_when_load_not_supported(sample_skills):
    """Test fallback to list_skills() when backend doesn't support load_skills()."""
    from myrm_agent_harness.agent.skill_agent import SkillAgent

    llm = MagicMock()
    backend = MockSkillBackendNoLoadSupport(sample_skills)

    agent = SkillAgent(
        llm=llm,
        skill_backend=backend,
        desired_skill_ids=["skill1"],  # Backend doesn't support load_skills()
    )

    skills = await agent._get_cached_skills()
    assert len(skills) == 3  # Fallback loads all
    assert {s.name for s in skills} == {"skill1", "skill2", "skill3"}


@pytest.mark.asyncio
async def test_hot_reload_fetches_each_time(sample_skills):
    """Test _get_cached_skills fetches from backend each time (hot-reload support)."""
    from myrm_agent_harness.agent.skill_agent import SkillAgent

    llm = MagicMock()
    backend = MockSkillBackend(sample_skills)

    agent = SkillAgent(llm=llm, skill_backend=backend, desired_skill_ids=["skill1"])

    skills1 = await agent._get_cached_skills()
    skills2 = await agent._get_cached_skills()

    assert len(skills1) == 1
    assert len(skills2) == 1
    assert skills1[0].name == "skill1"
