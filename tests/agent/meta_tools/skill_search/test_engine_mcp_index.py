"""Tests for MCP skill BM25 index enrichment in SkillSearchEngine."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.skills.search.engine import (
    MCP_SKILL_TOOL_INDEX_THRESHOLD,
    SkillSearchEngine,
    _build_skill_index_document,
    _truncate_tool_desc,
)
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata


def _mcp_skill(tool_count: int, *, user_description: str = "GitHub integration") -> SkillMetadata:
    tools = [f"tool_{i}" for i in range(tool_count)]
    tool_schemas: dict[str, dict[str, object]] = {}
    for name in tools:
        tool_schemas[name] = {
            "description": f"Does {name} on repository",
            "inputSchema": {},
        }
    return SkillMetadata(
        name="mcp_github_skill",
        description=user_description,
        mcp=MCPSkillData(server="github", tools=tools, config=[], tool_schemas=tool_schemas),
    )


class TestBuildSkillIndexDocument:
    def test_small_mcp_skill_uses_base_only(self) -> None:
        skill = _mcp_skill(MCP_SKILL_TOOL_INDEX_THRESHOLD)
        doc = _build_skill_index_document(skill)
        assert "tool_0" not in doc
        assert "GitHub integration" in doc

    def test_large_mcp_skill_includes_tool_names(self) -> None:
        skill = _mcp_skill(MCP_SKILL_TOOL_INDEX_THRESHOLD + 1)
        doc = _build_skill_index_document(skill)
        assert "tool_0" in doc
        assert "tool_3" in doc

    def test_tool_without_schema_dict_uses_name_token(self) -> None:
        skill = _mcp_skill(MCP_SKILL_TOOL_INDEX_THRESHOLD + 1)
        assert skill.mcp is not None
        skill.mcp.tool_schemas["tool_0"] = "not-a-dict"  # type: ignore[assignment]
        doc = _build_skill_index_document(skill)
        assert "tool 0" in doc

    def test_tool_with_non_string_description(self) -> None:
        skill = _mcp_skill(MCP_SKILL_TOOL_INDEX_THRESHOLD + 1)
        assert skill.mcp is not None
        skill.mcp.tool_schemas["tool_0"] = {"description": 123, "inputSchema": {}}
        doc = _build_skill_index_document(skill)
        assert "tool 0" in doc


class TestTruncateToolDesc:
    def test_empty_description(self) -> None:
        assert _truncate_tool_desc("") == ""

    def test_sentence_boundary_clip(self) -> None:
        text = "First sentence. " + "x" * 200
        clipped = _truncate_tool_desc(text, max_chars=40)
        assert clipped.endswith(".")
        assert len(clipped) <= 40

    def test_word_boundary_ellipsis(self) -> None:
        text = "alpha beta gamma delta epsilon zeta eta theta"
        clipped = _truncate_tool_desc(text, max_chars=20)
        assert clipped.endswith("…")


class TestSkillSearchEngineRegexLimit:
    def test_regex_search_respects_top_k(self) -> None:
        skills = [SkillMetadata(name=f"skill_{i}", description=f"match keyword {i}") for i in range(5)]
        engine = SkillSearchEngine(skills)
        results = engine.search_regex("match", top_k=2)
        assert len(results) == 2
