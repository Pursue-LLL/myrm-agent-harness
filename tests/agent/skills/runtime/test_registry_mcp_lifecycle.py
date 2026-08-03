"""SkillRegistry MCP lifecycle tests."""

from __future__ import annotations

from myrm_agent_harness.agent.skills.runtime.registry import SkillRegistry
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata


def _mcp_skill(name: str) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=f"MCP skill {name}",
        mcp=MCPSkillData(server=name, tools=[], config=[]),
    )


def _storage_skill(name: str) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=f"Storage skill {name}",
        storage_skill_id=f"skill_{name}",
        storage_path=f"/skills/{name}",
    )


def test_clear_mcp_skills_removes_only_mcp_entries() -> None:
    registry = SkillRegistry()
    registry.register(_mcp_skill("github_mcp"))
    registry.register(_mcp_skill("notion_mcp"))
    registry.register(_storage_skill("user_skill"))

    registry.clear_mcp_skills()

    assert registry.get_skill("github_mcp") is None
    assert registry.get_skill("notion_mcp") is None
    assert registry.get_skill("user_skill") is not None


def test_clear_mcp_skills_is_noop_when_empty() -> None:
    registry = SkillRegistry()
    registry.register(_storage_skill("only_storage"))

    registry.clear_mcp_skills()

    assert registry.get_skill("only_storage") is not None
