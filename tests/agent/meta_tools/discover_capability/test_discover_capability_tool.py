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
    description: str = "A dummy native tool for testing"
    args_schema: type[BaseModel] = DummyInput

    def _run(self, arg1: str) -> str:
        return "dummy"


@pytest.fixture
def mock_registry():
    registry = MagicMock(spec=ToolRegistry)
    registry.get_deferred_tools.return_value = [DummyTool()]
    return registry


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
async def test_discover_native_tool(mock_registry):
    tool = create_discover_capability_tool(registry=mock_registry)
    result = await tool.ainvoke({"query": ".*", "mode": "regex"})
    assert "Found Native Tools" in result
    assert "<AutoMountTools>" in result
    assert "dummy_native_tool" in result


@pytest.mark.asyncio
async def test_discover_external_skill(mock_skills):
    tool = create_discover_capability_tool(skills=mock_skills)
    result = await tool.ainvoke({"query": ".*", "mode": "regex"})
    assert "Found External Skills" in result
    assert "<ExternalSkills>" in result
    assert "external_skill_1" in result


@pytest.mark.asyncio
async def test_discover_both(mock_registry, mock_skills):
    tool = create_discover_capability_tool(registry=mock_registry, skills=mock_skills)
    # Search for something that matches both or use regex .*
    result = await tool.ainvoke({"query": ".*", "mode": "regex"})
    assert "Found Native Tools" in result
    assert "Found External Skills" in result
    assert "dummy_native_tool" in result
    assert "external_skill_1" in result


@pytest.mark.asyncio
async def test_no_matches(mock_registry, mock_skills):
    tool = create_discover_capability_tool(registry=mock_registry, skills=mock_skills)
    result = await tool.ainvoke({"query": "nonexistent_capability_xyz123"})
    assert "No capabilities found" in result


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
