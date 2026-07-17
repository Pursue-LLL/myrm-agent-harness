"""Tests for discover_capability_tool registry sync."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    sync_discover_capability_tool,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.backends.skills.types import SkillMetadata


@pytest.mark.asyncio
async def test_sync_registers_discover_when_skills_present() -> None:
    """discover_capability_tool is registered when searchable skills exist."""
    registry = ToolRegistry()
    skills = [SkillMetadata(name="github_pr", description="GitHub PR operations")]
    sync_discover_capability_tool(registry, skills=skills)
    assert registry.has_tool("discover_capability_tool")


@pytest.mark.asyncio
async def test_sync_does_not_register_discover_when_no_skills() -> None:
    """discover_capability_tool is NOT registered when no searchable skills."""
    registry = ToolRegistry()
    sync_discover_capability_tool(registry)
    assert not registry.has_tool("discover_capability_tool")


@pytest.mark.asyncio
async def test_sync_removes_stale_discover_tool() -> None:
    """Re-sync removes stale discover_capability_tool when skills become empty."""
    registry = ToolRegistry()
    skills = [SkillMetadata(name="github_pr", description="GitHub PR operations")]
    sync_discover_capability_tool(registry, skills=skills)
    assert registry.has_tool("discover_capability_tool")

    sync_discover_capability_tool(registry, skills=[])
    assert not registry.has_tool("discover_capability_tool")
