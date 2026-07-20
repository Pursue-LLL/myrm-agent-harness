"""Registry ↔ SkillAgent wiring integration for skill tool boundary descriptions.

Verifies get_meta_tools + sync_discover_capability_tool and SkillAgent._build_tools
expose discover_capability_tool and skill_discovery_tool with mutual cross-references.
Key path uses real ToolRegistry and stub protocol backends (no MagicMock on registry wiring).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    sync_discover_capability_tool,
)
from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry, ToolSource
from myrm_agent_harness.backends.skills.types import SkillMetadata

_DISCOVER_TOOL = "discover_capability_tool"
_MARKETPLACE_TOOL = "skill_discovery_tool"


class _StubSkillBackend:
    """Minimal SkillBackend stub for list_skills only."""

    def __init__(self, skills: list[SkillMetadata]) -> None:
        self._skills = skills

    async def list_skills(self) -> list[SkillMetadata]:
        return list(self._skills)

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        by_name = {skill.name: skill for skill in self._skills}
        return [by_name[skill_id] for skill_id in skill_ids if skill_id in by_name]

    async def get_skill_content(self, skill_name: str) -> str:
        return f"# {skill_name}\n"

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        return b""


class _StubDiscoveryBackend:
    """Minimal discovery backend so skill_discovery_tool mounts Turn1 eager."""

    async def install_from_url(self, url: str, user_id: str) -> dict[str, object]:
        return {"url": url, "user_id": user_id}

    async def uninstall(self, skill_id: str, user_id: str) -> dict[str, object]:
        return {"skill_id": skill_id, "user_id": user_id}


def _sample_skill() -> SkillMetadata:
    return SkillMetadata(
        name="github_pr",
        description="GitHub pull request operations",
        model_invocable=True,
        available=True,
    )


def _tool_description_by_name(tools: list[object], name: str) -> str:
    tool = next(t for t in tools if getattr(t, "name", None) == name)
    description = getattr(tool, "description", None)
    assert isinstance(description, str) and description.strip()
    return description


def _assert_mutual_boundary(descriptions: tuple[str, str]) -> None:
    discover_description, marketplace_description = descriptions
    assert _MARKETPLACE_TOOL in discover_description
    assert _DISCOVER_TOOL in marketplace_description
    assert "bound" in discover_description.lower()
    assert "bound" in marketplace_description.lower()


@pytest.mark.integration
def test_registry_wiring_exposes_skill_tools_with_boundary_descriptions() -> None:
    """get_meta_tools + sync_discover registers both tools with cross-referenced descriptions."""
    skills = [_sample_skill()]
    registry = ToolRegistry()
    skill_backend = _StubSkillBackend(skills)
    discovery_backend = _StubDiscoveryBackend()

    meta_tools = get_meta_tools(
        skills,
        skill_backend,
        registry=registry,
        discovery_backend=discovery_backend,
        enable_file_tools=False,
        enable_bash=False,
        enable_answer_tool=False,
    )
    registry.register_many(meta_tools, source=ToolSource.META)
    sync_discover_capability_tool(registry, skills=skills)

    resolved = registry.resolve()
    resolved_names = {t.name for t in resolved}
    assert _MARKETPLACE_TOOL in resolved_names
    assert _DISCOVER_TOOL in resolved_names

    _assert_mutual_boundary(
        (
            _tool_description_by_name(resolved, _DISCOVER_TOOL),
            _tool_description_by_name(resolved, _MARKETPLACE_TOOL),
        )
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_skill_agent_build_tools_wires_boundary_descriptions() -> None:
    """SkillAgent._build_tools resolves the same boundary descriptions end-to-end."""
    skills = [_sample_skill()]
    agent = SkillAgent(
        llm=AsyncMock(),
        skill_backend=_StubSkillBackend(skills),
        discovery_backend=_StubDiscoveryBackend(),
        enable_file_tools=False,
        enable_bash=False,
        enable_answer_tool=False,
    )

    tools = await agent._build_tools()
    tool_names = {t.name for t in tools}
    assert _MARKETPLACE_TOOL in tool_names
    assert _DISCOVER_TOOL in tool_names

    _assert_mutual_boundary(
        (
            _tool_description_by_name(tools, _DISCOVER_TOOL),
            _tool_description_by_name(tools, _MARKETPLACE_TOOL),
        )
    )
