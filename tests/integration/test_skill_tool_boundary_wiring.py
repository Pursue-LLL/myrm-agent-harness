"""Registry ↔ SkillAgent wiring integration for skill tool boundary descriptions.

Verifies get_meta_tools + sync_discover_capability_tool and SkillAgent._build_tools
expose skill_search_tool and skill_market_tool with mutual cross-references.
Key path uses real ToolRegistry and stub protocol backends (no MagicMock on registry wiring).
"""

from __future__ import annotations
from myrm_agent_harness.agent.meta_tools.mount_policy import FileAccessMode

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    sync_discover_capability_tool,
)
from myrm_agent_harness.agent.meta_tools.skills.market.skill_market_tool import (
    create_skill_market_tool,
)
from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry, ToolSource
from myrm_agent_harness.backends.skills.types import SkillMetadata

_DISCOVER_TOOL = "skill_search_tool"
_MARKETPLACE_TOOL = "skill_market_tool"


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


class _StubMarketBackend:
    """Minimal discovery backend so skill_market_tool mounts Turn1 eager."""

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


def _mount_market_tool(
    market_backend: _StubMarketBackend,
) -> object:
    install_url_fn = getattr(market_backend, "install_from_url", None)
    uninstall_fn = getattr(market_backend, "uninstall", None)
    return create_skill_market_tool(
        market_backend,
        install_from_url_fn=install_url_fn,
        uninstall_fn=uninstall_fn,
    )


@pytest.mark.integration
def test_registry_wiring_exposes_skill_tools_with_boundary_descriptions() -> None:
    """user_tools skill_market + get_meta_tools registers both tools with cross-referenced descriptions."""
    skills = [_sample_skill()]
    registry = ToolRegistry()
    skill_backend = _StubSkillBackend(skills)
    market_backend = _StubMarketBackend()

    meta_tools = get_meta_tools(
        skills,
        skill_backend,
        registry=registry,
        file_access_mode=FileAccessMode.NONE,
        enable_shell_tools=False,
        enable_answer_tool=False,
    )
    registry.register_many(meta_tools, source=ToolSource.META)
    registry.register(_mount_market_tool(market_backend), source=ToolSource.USER)
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
        market_backend=_StubMarketBackend(),
        file_access_mode=FileAccessMode.NONE,
        enable_shell_tools=False,
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


@pytest.mark.integration
def test_discover_description_omits_market_tool_when_market_not_mounted() -> None:
    """skill_search_tool must not ghost-reference skill_market_tool when market is off."""
    skills = [_sample_skill()]
    registry = ToolRegistry()
    meta_tools = get_meta_tools(
        skills,
        _StubSkillBackend(skills),
        registry=registry,
        file_access_mode=FileAccessMode.NONE,
        enable_shell_tools=False,
        enable_answer_tool=False,
    )
    registry.register_many(meta_tools, source=ToolSource.META)
    sync_discover_capability_tool(registry, skills=skills)

    description = _tool_description_by_name(registry.resolve(), _DISCOVER_TOOL)
    assert _MARKETPLACE_TOOL not in description
    assert "Settings" in description or "Discover" in description


@pytest.mark.integration
def test_registry_omits_marketplace_tool_without_user_mount() -> None:
    """skill_market_tool mounts only when registered via user_tools (server mount)."""
    skills = [_sample_skill()]
    registry = ToolRegistry()
    meta_tools = get_meta_tools(
        skills,
        _StubSkillBackend(skills),
        registry=registry,
        file_access_mode=FileAccessMode.NONE,
        enable_shell_tools=False,
        enable_answer_tool=False,
    )
    registry.register_many(meta_tools, source=ToolSource.META)
    sync_discover_capability_tool(registry, skills=skills)

    resolved_names = {t.name for t in registry.resolve()}
    assert _DISCOVER_TOOL in resolved_names
    assert _MARKETPLACE_TOOL not in resolved_names


@pytest.mark.integration
def test_registry_omits_discover_tool_when_no_searchable_skills() -> None:
    """skill_search_tool is absent when sync receives no model_invocable skills."""
    registry = ToolRegistry()
    meta_tools = get_meta_tools(
        [],
        _StubSkillBackend([]),
        registry=registry,
        file_access_mode=FileAccessMode.NONE,
        enable_shell_tools=False,
        enable_answer_tool=False,
    )
    registry.register_many(meta_tools, source=ToolSource.META)
    registry.register(_mount_market_tool(_StubMarketBackend()), source=ToolSource.USER)
    sync_discover_capability_tool(registry, skills=[])

    resolved_names = {t.name for t in registry.resolve()}
    assert _MARKETPLACE_TOOL in resolved_names
    assert _DISCOVER_TOOL not in resolved_names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discover_runtime_returns_bound_skills_xml() -> None:
    """Runtime hit path wraps results in BoundSkills (not ExternalSkills)."""
    skills = [_sample_skill()]
    registry = ToolRegistry()
    meta_tools = get_meta_tools(
        skills,
        _StubSkillBackend(skills),
        registry=registry,
        file_access_mode=FileAccessMode.NONE,
        enable_shell_tools=False,
        enable_answer_tool=False,
    )
    registry.register_many(meta_tools, source=ToolSource.META)
    registry.register(_mount_market_tool(_StubMarketBackend()), source=ToolSource.USER)
    sync_discover_capability_tool(registry, skills=skills)

    discover = next(t for t in registry.resolve() if t.name == _DISCOVER_TOOL)
    result = await discover.ainvoke({"query": "github", "mode": "regex"})
    assert "<BoundSkills>" in result
    assert "<ExternalSkills>" not in result
    assert "github_pr" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discover_runtime_bm25_synonym_expansion_finds_skill() -> None:
    """BM25 + SynonymExpander through skill_search_tool on mock_skills corpus."""
    from tests.agent.meta_tools.skill_search.fixtures import (
        create_comprehensive_mock_skills,
    )

    skills = create_comprehensive_mock_skills()
    registry = ToolRegistry()
    meta_tools = get_meta_tools(
        skills,
        _StubSkillBackend(skills),
        registry=registry,
        file_access_mode=FileAccessMode.NONE,
        enable_shell_tools=False,
        enable_answer_tool=False,
    )
    registry.register_many(meta_tools, source=ToolSource.META)
    registry.register(_mount_market_tool(_StubMarketBackend()), source=ToolSource.USER)
    sync_discover_capability_tool(registry, skills=skills)

    discover = next(t for t in registry.resolve() if t.name == _DISCOVER_TOOL)
    result = await discover.ainvoke({"query": "auth", "mode": "bm25"})
    assert "<BoundSkills>" in result
    assert any(name in result for name in ("oauth_auth", "jwt_auth", "session_auth"))
    assert "No capabilities found" not in result


_SELECT_TOOL = "skill_select_tool"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_skill_select_static_description_and_catalog_delivery_wiring() -> None:
    """get_meta_tools static skill_select + SkillAgent stream catalog reinject (no tool XML)."""
    from langchain_core.messages import HumanMessage

    from myrm_agent_harness.agent._internals.agent_runtime import (
        apply_bound_skill_catalog_for_stream,
    )
    from myrm_agent_harness.agent.meta_tools.skills.select.skill_select_tool import (
        build_skill_select_static_description,
    )

    skills = [_sample_skill()]
    registry = ToolRegistry()
    meta_tools = get_meta_tools(
        skills,
        _StubSkillBackend(skills),
        registry=registry,
        file_access_mode=FileAccessMode.NONE,
        enable_shell_tools=False,
        enable_answer_tool=False,
    )
    select_tool = next(t for t in meta_tools if getattr(t, "name", None) == _SELECT_TOOL)
    description = select_tool.description or ""
    assert description.rstrip() == build_skill_select_static_description().rstrip()
    assert "github_pr" not in description
    assert "<skills>" not in description
    assert "hidden_count" in description

    agent = SkillAgent(llm=AsyncMock(), skill_backend=_StubSkillBackend(skills))
    messages = [HumanMessage(content="plan a PR review")]
    await apply_bound_skill_catalog_for_stream(messages, agent)

    first = messages[0]
    assert isinstance(first.content, str)
    assert first.content.startswith("<bound_skills")
    assert "github_pr" in first.content
    assert "plan a PR review" in first.content
