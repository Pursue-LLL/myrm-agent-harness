"""Tests for discover_capability_tool registry sync."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    sync_discover_capability_tool,
)
from myrm_agent_harness.agent.skills.runtime.catalog_display import (
    SKILL_INLINE_THRESHOLD,
    should_mount_skill_search_tool,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.backends.skills.types import SkillMetadata


def _skill(name: str) -> SkillMetadata:
    return SkillMetadata(name=name, description=f"desc for {name}", model_invocable=True)


def _many_skills(count: int) -> list[SkillMetadata]:
    return [_skill(f"bound_skill_{index:02d}") for index in range(count)]


@pytest.mark.asyncio
async def test_sync_registers_discover_when_hidden_skills_exist() -> None:
    """skill_search_tool mounts only when hidden_count > 0."""
    registry = ToolRegistry()
    skills = _many_skills(21)
    sync_discover_capability_tool(registry, skills=skills)
    assert registry.has_tool("skill_search_tool")


@pytest.mark.asyncio
async def test_skill_search_mount_threshold_boundary_at_inline_limit() -> None:
    """Gate must not mount at SKILL_INLINE_THRESHOLD; must mount at threshold + 1."""
    at_limit = _many_skills(SKILL_INLINE_THRESHOLD)
    above_limit = _many_skills(SKILL_INLINE_THRESHOLD + 1)

    assert not should_mount_skill_search_tool(at_limit)
    assert should_mount_skill_search_tool(above_limit)

    registry_at = ToolRegistry()
    sync_discover_capability_tool(registry_at, skills=at_limit)
    assert not registry_at.has_tool("skill_search_tool")

    registry_above = ToolRegistry()
    sync_discover_capability_tool(registry_above, skills=above_limit)
    assert registry_above.has_tool("skill_search_tool")


@pytest.mark.asyncio
async def test_sync_skips_discover_when_all_skills_inline() -> None:
    """≤20 inline skills must not mount skill_search_tool (203 tok saved when unmounted)."""
    registry = ToolRegistry()
    skills = _many_skills(5)
    assert not should_mount_skill_search_tool(skills)
    sync_discover_capability_tool(registry, skills=skills)
    assert not registry.has_tool("skill_search_tool")


@pytest.mark.asyncio
async def test_sync_does_not_register_discover_when_no_skills() -> None:
    """discover_capability_tool is NOT registered when no searchable skills."""
    registry = ToolRegistry()
    sync_discover_capability_tool(registry)
    assert not registry.has_tool("skill_search_tool")


@pytest.mark.asyncio
async def test_sync_removes_stale_discover_tool() -> None:
    """Re-sync removes stale skill_search_tool when hidden_count drops to zero."""
    registry = ToolRegistry()
    skills = _many_skills(21)
    sync_discover_capability_tool(registry, skills=skills)
    assert registry.has_tool("skill_search_tool")

    sync_discover_capability_tool(registry, skills=_many_skills(3))
    assert not registry.has_tool("skill_search_tool")


@pytest.mark.asyncio
async def test_sync_respects_skill_configs_parity() -> None:
    """is_core filtering can force hidden_count > 0 even with few total skills."""
    registry = ToolRegistry()
    skills = _many_skills(3)
    skill_configs = {
        skills[0].id: {"is_core": True},
        skills[1].id: {"is_core": False},
        skills[2].id: {"is_core": False},
    }
    assert should_mount_skill_search_tool(skills, skill_configs=skill_configs)
    sync_discover_capability_tool(registry, skills=skills, skill_configs=skill_configs)
    assert registry.has_tool("skill_search_tool")
