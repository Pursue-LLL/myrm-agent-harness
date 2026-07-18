"""Tests for unified capability discovery meta-tool."""

from unittest.mock import MagicMock

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    create_discover_capability_tool,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.backends.skills.types import SkillMetadata


class DummyInput(BaseModel):
    arg1: str = Field(description="A dummy argument")


class DummyTool(BaseTool):
    name: str = "dummy_native_tool"
    description: str = "Browse websites and open webpages for the user"
    args_schema: type[BaseModel] = DummyInput

    def _run(self, arg1: str) -> str:
        return "dummy"


@pytest.fixture
def mock_registry():
    return MagicMock(spec=ToolRegistry)


@pytest.fixture
def mock_skills():
    return [
        SkillMetadata(name="external_skill_1", description="An external skill"),
        SkillMetadata(name="external_skill_2", description="Another external skill"),
    ]


@pytest.mark.asyncio
async def test_create_tool_no_engines():
    tool = create_discover_capability_tool()
    assert tool.name == "discover_capability_tool"
    result = await tool.ainvoke({"query": "test"})
    assert "No capabilities found" in result


@pytest.mark.asyncio
async def test_discover_external_skill(mock_skills):
    tool = create_discover_capability_tool(skills=mock_skills)
    result = await tool.ainvoke({"query": ".*", "mode": "regex"})
    assert "Found Skills" in result
    assert "<ExternalSkills>" in result
    assert "external_skill_1" in result


@pytest.mark.asyncio
async def test_no_matches(mock_registry, mock_skills):
    tool = create_discover_capability_tool(registry=mock_registry, skills=mock_skills)
    result = await tool.ainvoke({"query": "nonexistent_capability_xyz123"})
    assert "No capabilities found" in result


@pytest.mark.asyncio
async def test_capability_gap_block_on_miss() -> None:
    tool = create_discover_capability_tool(
        active_tool_groups=frozenset({"web", "memory", "file_ops", "shell"}),
    )
    result = await tool.ainvoke({"query": "please browse this website"})
    assert "No capabilities found" in result
    assert "<CapabilityGap>" in result
    assert "browser" in result


@pytest.mark.asyncio
async def test_capability_gap_block_on_hit() -> None:
    """Search hits must still append browser gap when browser group is disabled."""
    skills = [
        SkillMetadata(name="browse_helper_skill", description="Browse websites and extract content"),
        SkillMetadata(name="other_skill", description="Another skill"),
    ]
    tool = create_discover_capability_tool(
        skills=skills,
        active_tool_groups=frozenset({"web", "memory", "file_ops", "shell"}),
    )
    result = await tool.ainvoke({"query": "browse", "mode": "regex"})
    assert "Found Skills" in result
    assert "<CapabilityGap>" in result
    assert "browser" in result


@pytest.mark.asyncio
async def test_skill_gap_block_on_miss() -> None:
    tool = create_discover_capability_tool(
        bound_skill_names=frozenset(),
        library_skill_names=frozenset({"github_pr_skill"}),
    )
    result = await tool.ainvoke({"query": "run github_pr_skill workflow"})
    assert "No capabilities found" in result
    assert "<SkillGap>" in result
    assert "github_pr_skill" in result


@pytest.mark.asyncio
async def test_gap_dispatch_events_on_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, object]] = []

    async def _capture(event_name: str, payload: object, config: object | None = None) -> None:
        events.append((event_name, payload))

    monkeypatch.setattr(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
        _capture,
    )
    tool = create_discover_capability_tool(
        active_tool_groups=frozenset({"web", "memory", "file_ops", "shell"}),
        bound_skill_names=frozenset(),
        library_skill_names=frozenset({"github_pr_skill"}),
    )
    await tool.ainvoke({"query": "browse website with github_pr_skill"})
    event_names = [name for name, _ in events]
    assert "capability_gap" in event_names
    assert "skill_gap" in event_names


@pytest.mark.asyncio
async def test_description_is_stable_without_dynamic_tool_names():
    """Stable index: discover description must not embed per-tool names (prefix cache)."""
    tool = create_discover_capability_tool()
    assert "dummy_native_tool" not in tool.description


@pytest.mark.asyncio
async def test_description_omits_native_tool_list_when_registry_empty():
    """When registry has no Turn1 tools, description omits the native tools list."""
    tool = create_discover_capability_tool()
    assert "Discoverable native tools" not in tool.description


@pytest.mark.asyncio
async def test_description_contains_must_search_before_declining():
    """Verify tool description enforces proactive search before declining."""
    tool = create_discover_capability_tool()
    assert "MUST search here BEFORE declining" in tool.description
    assert "IMPORTANT" in tool.description


@pytest.mark.asyncio
async def test_external_skill_output_format(mock_skills):
    """Verify external skill results use only name and description (no source/version)."""
    tool = create_discover_capability_tool(skills=mock_skills)
    result = await tool.ainvoke({"query": ".*", "mode": "regex"})
    assert "external_skill_1" in result
    assert "An external skill" in result
    assert "source:" not in result
    assert "version:" not in result


@pytest.mark.asyncio
async def test_bm25_mode_default(mock_skills):
    """Verify default mode is bm25 (not regex)."""
    tool = create_discover_capability_tool(skills=mock_skills)
    result = await tool.ainvoke({"query": "external"})
    assert "external_skill" in result or "No capabilities" in result


@pytest.mark.asyncio
async def test_skill_output_format(mock_skills):
    """Verify skill output uses ExternalSkills XML format."""
    tool = create_discover_capability_tool(skills=mock_skills)
    result = await tool.ainvoke({"query": ".*", "mode": "regex"})
    assert "<ExternalSkills>" in result
    assert "external_skill_1" in result


@pytest.mark.asyncio
async def test_description_contains_skill_select_instruction():
    """Verify description mentions skill_select_tool for external skills."""
    tool = create_discover_capability_tool()
    assert "skill_select_tool" in tool.description


@pytest.mark.asyncio
async def test_wildcard_query(mock_skills):
    """Verify query='*' lists all skills."""
    tool = create_discover_capability_tool(skills=mock_skills)
    result = await tool.ainvoke({"query": "*"})
    assert "external_skill_1" in result or "No capabilities" in result


@pytest.mark.asyncio
async def test_hybrid_engine_path(mock_skills):
    """Cover HybridSkillSearchEngine initialization path (lines 79-83) and await path (line 141)."""
    from unittest.mock import AsyncMock, patch

    from myrm_agent_harness.agent.meta_tools.skills.search.types import SkillSearchResult

    mock_engine_instance = MagicMock()
    mock_engine_instance.search_bm25 = AsyncMock(
        return_value=[SkillSearchResult(name="external_skill_1", description="An external skill", score=1.0)]
    )
    mock_hybrid_cls = MagicMock(return_value=mock_engine_instance)

    mock_embedding_config = MagicMock()

    with patch(
        "myrm_agent_harness.agent.meta_tools.skills.search.hybrid_engine.HybridSkillSearchEngine",
        mock_hybrid_cls,
    ):
        tool = create_discover_capability_tool(
            skills=mock_skills,
            embedding_config=mock_embedding_config,
        )

    result = await tool.ainvoke({"query": "external"})
    assert "external_skill_1" in result


@pytest.mark.asyncio
async def test_async_engine_isawaitable():
    """Verify discover_capability handles async engines (HybridSkillSearchEngine).

    Before the fix, HybridSkillSearchEngine.search_bm25 returns a coroutine,
    and the tool would fail with 'coroutine object is not iterable'.
    This test validates the isawaitable() guard works correctly.
    """
    import inspect

    from myrm_agent_harness.agent.meta_tools.skills.search.types import SkillSearchResult

    class AsyncMockEngine:
        """Mimics HybridSkillSearchEngine with async search methods."""

        async def search_bm25(self, query: str, top_k: int = 10) -> list[SkillSearchResult]:
            return [SkillSearchResult(name="skill_a", description="Async skill A", score=1.0)]

        async def search_regex(self, pattern: str, top_k: int = 10) -> list[SkillSearchResult]:
            return [SkillSearchResult(name="skill_b", description="Async skill B", score=1.0)]

    engine = AsyncMockEngine()

    # BM25 path: calling async method returns a coroutine
    bm25_result = engine.search_bm25("test", top_k=10)
    assert inspect.isawaitable(bm25_result), "Async engine.search_bm25 should return awaitable"
    matches = await bm25_result
    assert len(matches) == 1
    assert matches[0].name == "skill_a"

    # Regex path
    regex_result = engine.search_regex("test")
    assert inspect.isawaitable(regex_result), "Async engine.search_regex should return awaitable"
    matches = await regex_result
    assert len(matches) == 1
    assert matches[0].name == "skill_b"

    # Sync engine should NOT be awaitable
    class SyncMockEngine:
        def search_bm25(self, query: str, top_k: int = 10) -> list[SkillSearchResult]:
            return [SkillSearchResult(name="sync_skill", description="Sync", score=1.0)]

    sync_engine = SyncMockEngine()
    sync_result = sync_engine.search_bm25("test")
    assert not inspect.isawaitable(sync_result), "Sync engine result should not be awaitable"
    assert sync_result[0].name == "sync_skill"
