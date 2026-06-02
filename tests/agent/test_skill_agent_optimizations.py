"""Test SkillAgent _get_cached_skills behavior.

Verifies hot-reload semantics: every call to _get_cached_skills fetches from backend.
"""

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.skills import SkillMetadata


@pytest.mark.asyncio
async def test_skills_always_fetched_from_backend():
    """Each call to _get_cached_skills queries the backend (hot-reload support)."""
    mock_skill_backend = AsyncMock()
    mock_skill_backend.list_skills = AsyncMock(
        return_value=[
            SkillMetadata(name="skill1", description="Test skill 1"),
            SkillMetadata(name="skill2", description="Test skill 2"),
        ]
    )

    mock_llm = AsyncMock()

    agent = SkillAgent(llm=mock_llm, skill_backend=mock_skill_backend)

    skills1 = await agent._get_cached_skills()
    assert len(skills1) == 2
    assert mock_skill_backend.list_skills.call_count == 1

    skills2 = await agent._get_cached_skills()
    assert len(skills2) == 2
    assert mock_skill_backend.list_skills.call_count == 2


@pytest.mark.asyncio
async def test_skills_build_tools_calls_backend():
    """_build_tools fetches skills from backend each time."""
    mock_skill_backend = AsyncMock()
    mock_skill_backend.list_skills = AsyncMock(
        return_value=[
            SkillMetadata(name="test_skill", description="Test skill"),
        ]
    )

    mock_llm = AsyncMock()

    agent = SkillAgent(llm=mock_llm, skill_backend=mock_skill_backend)

    await agent._get_cached_skills()
    assert mock_skill_backend.list_skills.call_count == 1

    tools = await agent._build_tools()
    assert mock_skill_backend.list_skills.call_count == 2
    assert isinstance(tools, list)


@pytest.mark.asyncio
async def test_skills_get_storage_paths_calls_backend():
    """_get_skill_storage_paths fetches skills from backend each time."""
    mock_skill_backend = AsyncMock()
    mock_skill_backend.list_skills = AsyncMock(
        return_value=[
            SkillMetadata(name="skill1", description="Test skill", storage_path="skill1_storage"),
        ]
    )

    mock_llm = AsyncMock()

    agent = SkillAgent(llm=mock_llm, skill_backend=mock_skill_backend)

    await agent._get_cached_skills()
    assert mock_skill_backend.list_skills.call_count == 1

    paths = await agent._get_skill_storage_paths()
    assert mock_skill_backend.list_skills.call_count == 2
    assert isinstance(paths, list)


@pytest.mark.asyncio
async def test_skills_backend_exception_returns_empty_list():
    """When backend raises, _get_cached_skills returns empty list."""
    mock_skill_backend = AsyncMock()
    mock_skill_backend.list_skills = AsyncMock(side_effect=Exception("Backend error"))

    mock_llm = AsyncMock()

    agent = SkillAgent(llm=mock_llm, skill_backend=mock_skill_backend)

    skills = await agent._get_cached_skills()
    assert skills == []
    assert mock_skill_backend.list_skills.call_count == 1

    skills2 = await agent._get_cached_skills()
    assert skills2 == []
    assert mock_skill_backend.list_skills.call_count == 2
