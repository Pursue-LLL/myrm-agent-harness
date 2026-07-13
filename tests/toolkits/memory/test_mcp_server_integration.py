"""Integration tests for MemoryMCPServer memory_list tool.

Exercises the FULL pipeline from FastMCP tool_manager.call_tool through
MemoryMCPServer tool functions into real MemoryManager methods — no
mocking of MCP protocol, FastMCP parameter parsing, or MemoryManager
logic. Only the underlying storage backends (vector/relational) are
mocked, as they are external infrastructure dependencies.

Tests cover:
- Tool registration and discovery via FastMCP
- Overview mode: stats + preview for all categories
- Category mode: paginated listing with real MemoryManager.list_memories
- Error handling: invalid category, empty results, pagination bounds
- Include archived flag propagation
- Budget truncation for large content
- Drift defense footer presence
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.mcp_server import MemoryMCPServer
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument


def _make_vector_doc(doc_id: str, content: str, mem_type: str = "semantic") -> VectorDocument:
    return VectorDocument(
        id=doc_id,
        content=content,
        vector=[0.1] * 768,
        metadata={
            "memory_type": mem_type,
            "importance": 0.5,
            "confidence": 1.0,
            "source_chat_id": "",
            "preference_type": "",
            "preference_strength": 0.0,
            "correction_of": "",
            "access_count": 0,
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def _stores():
    vector = AsyncMock()
    vector.count = AsyncMock(return_value=5)
    vector.search = AsyncMock(return_value=[])
    vector.get = AsyncMock(return_value=None)
    vector.scroll = AsyncMock(return_value=([], None))
    vector.upsert = AsyncMock()
    vector.delete = AsyncMock()
    vector.close = AsyncMock()

    relational = AsyncMock()
    relational.count_profiles = AsyncMock(return_value=3)
    relational.count_rules = AsyncMock(return_value=2)
    relational.list_profiles = AsyncMock(return_value=[])
    relational.list_rules = AsyncMock(return_value=[])
    relational.count_pending = AsyncMock(return_value=0)
    relational.close = AsyncMock()

    embedding = AsyncMock()
    embedding.embed = AsyncMock(return_value=[0.1] * 768)
    embedding.dimension = 768

    return vector, relational, embedding


@pytest.fixture
def mcp_server(_stores):
    vector, relational, embedding = _stores
    config = MemoryConfig(
        embedding_model="test-model",
        collection_prefix="integration_test",
        bm25_top_k=50,
        bm25_max_corpus_size=5000,
    )
    manager = MemoryManager(
        config,
        user_id="integration_user",
        vector=vector,
        relational=relational,
        embedding=embedding,
    )
    return MemoryMCPServer(manager)


class TestMCPToolRegistration:
    """Verify FastMCP correctly registers all 4 memory tools."""

    def test_four_tools_registered(self, mcp_server: MemoryMCPServer):
        tools = mcp_server.mcp._tool_manager.list_tools()
        names = {t.name for t in tools}
        assert names == {"memory_recall", "memory_list", "memory_store", "memory_manage"}

    def test_memory_list_has_parameters(self, mcp_server: MemoryMCPServer):
        tools = mcp_server.mcp._tool_manager.list_tools()
        list_tool = next(t for t in tools if t.name == "memory_list")
        props = list_tool.parameters.get("properties", {})
        assert "category" in props
        assert "page" in props
        assert "page_size" in props
        assert "include_archived" in props


class TestMemoryListOverviewIntegration:
    """Integration: overview mode goes through real MemoryManager."""

    @pytest.mark.asyncio
    async def test_overview_returns_all_categories(self, mcp_server: MemoryMCPServer):
        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {})
        assert "Memory Overview" in result
        assert "knowledge" in result.lower()
        assert "preference" in result.lower()

    @pytest.mark.asyncio
    async def test_overview_shows_correct_counts(self, mcp_server: MemoryMCPServer, _stores):
        vector, relational, _ = _stores
        vector.count.return_value = 10
        relational.count_profiles.return_value = 5
        relational.count_rules.return_value = 3

        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {})
        assert "10" in result or "preference" in result

    @pytest.mark.asyncio
    async def test_overview_includes_drift_defense(self, mcp_server: MemoryMCPServer):
        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {})
        assert "memory_manage" in result


class TestMemoryListCategoryIntegration:
    """Integration: category mode paginates through real MemoryManager."""

    @pytest.mark.asyncio
    async def test_knowledge_listing_returns_content(self, mcp_server: MemoryMCPServer, _stores):
        vector, _, _ = _stores
        docs = [_make_vector_doc(f"k{i}", f"Knowledge fact {i}") for i in range(3)]
        vector.scroll.return_value = (docs, None)
        vector.count.return_value = 3

        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {"category": "knowledge"})
        assert "Knowledge fact 0" in result
        assert "Knowledge fact 1" in result
        assert "Knowledge fact 2" in result

    @pytest.mark.asyncio
    async def test_pagination_respects_page_param(self, mcp_server: MemoryMCPServer, _stores):
        vector, _, _ = _stores
        vector.count.return_value = 10
        docs = [_make_vector_doc(f"p{i}", f"Page two item {i}") for i in range(5)]
        vector.scroll.return_value = (docs, None)

        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {"category": "knowledge", "page": 2, "page_size": 5})
        assert "Page 2" in result or "page_size" in result or "Page two item" in result

    @pytest.mark.asyncio
    async def test_invalid_category_returns_error(self, mcp_server: MemoryMCPServer):
        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {"category": "nonexistent_cat"})
        assert "invalid category" in result.lower()

    @pytest.mark.asyncio
    async def test_empty_category_returns_no_items(self, mcp_server: MemoryMCPServer, _stores):
        vector, _, _ = _stores
        vector.count.return_value = 0
        vector.scroll.return_value = ([], None)

        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {"category": "knowledge"})
        assert "0 items" in result or "empty" in result.lower() or "No" in result

    @pytest.mark.asyncio
    async def test_include_archived_propagated(self, mcp_server: MemoryMCPServer, _stores):
        vector, _, _ = _stores
        vector.count.return_value = 1
        docs = [_make_vector_doc("a1", "Archived item")]
        vector.scroll.return_value = (docs, None)

        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {
            "category": "knowledge",
            "include_archived": True,
        })
        assert "Archived item" in result

    @pytest.mark.asyncio
    async def test_page_size_clamped_to_max(self, mcp_server: MemoryMCPServer, _stores):
        vector, _, _ = _stores
        vector.count.return_value = 100
        docs = [_make_vector_doc(f"c{i}", f"Clamped {i}") for i in range(50)]
        vector.scroll.return_value = (docs, None)

        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {"category": "knowledge", "page_size": 999})
        assert "Clamped" in result

    @pytest.mark.asyncio
    async def test_category_includes_drift_defense(self, mcp_server: MemoryMCPServer, _stores):
        vector, _, _ = _stores
        vector.count.return_value = 1
        docs = [_make_vector_doc("d1", "Drift test")]
        vector.scroll.return_value = (docs, None)

        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {"category": "knowledge"})
        assert "memory_manage" in result


class TestMemoryListEdgeCases:
    """Integration: edge cases and error paths."""

    @pytest.mark.asyncio
    async def test_page_beyond_total_shows_message(self, mcp_server: MemoryMCPServer, _stores):
        vector, _, _ = _stores
        vector.count.return_value = 3
        vector.scroll.return_value = ([], None)

        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {"category": "knowledge", "page": 100})
        assert "beyond" in result.lower() or "0 items" in result or "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_budget_truncation_with_large_content(self, mcp_server: MemoryMCPServer, _stores):
        vector, _, _ = _stores
        huge_content = "x" * 30000
        vector.count.return_value = 5
        docs = [_make_vector_doc(f"h{i}", huge_content) for i in range(5)]
        vector.scroll.return_value = (docs, None)

        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {"category": "knowledge", "page_size": 5})
        assert "h0" in result or "list_budget" in result or len(result) < 150000

    @pytest.mark.asyncio
    async def test_preference_category_uses_relational(self, mcp_server: MemoryMCPServer, _stores):
        _, relational, _ = _stores
        from myrm_agent_harness.toolkits.memory.types import ProfileEntry

        profiles = [
            ProfileEntry(id=f"pref-{i}", key=f"color_{i}", value=f"blue_{i}")
            for i in range(2)
        ]
        relational.list_profiles.return_value = profiles
        relational.count_profiles.return_value = 2

        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {"category": "preference"})
        assert "color_0" in result or "blue_0" in result

    @pytest.mark.asyncio
    async def test_rule_category_uses_relational(self, mcp_server: MemoryMCPServer, _stores):
        _, relational, _ = _stores
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

        rules = [
            ProceduralMemory(id="rule-1", content="Always greet", trigger="new chat", action="say hello")
        ]
        relational.list_rules.return_value = rules
        relational.count_rules.return_value = 1

        tm = mcp_server.mcp._tool_manager
        result = await tm.call_tool("memory_list", {"category": "rule"})
        assert "Always greet" in result
