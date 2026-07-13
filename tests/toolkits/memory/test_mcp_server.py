"""Tests for MemoryMCPServer adapter.

Validates MCP server initialization, tool registration, and tool execution
including edge cases (empty content, invalid types, clamped limits, profile
lookup, time bounds, categories, and memory management operations).
"""

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.mcp_server import (
    MemoryMCPServer,
    create_memory_mcp_server,
)
from myrm_agent_harness.toolkits.memory.types import (
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)


@pytest.fixture
def mock_manager():
    """Create a mock MemoryManager with essential attributes."""
    manager = AsyncMock()
    manager.search = AsyncMock(return_value=[])
    manager.store = AsyncMock()
    manager.has_relational = True
    manager.has_vector = True
    manager.approval_required = False
    manager.get_profile_attribute = AsyncMock(return_value=None)
    manager.add_knowledge = AsyncMock()
    manager.add_event = AsyncMock()
    manager.set_profile_attribute = AsyncMock(return_value=None)
    manager.add_rule = AsyncMock()
    manager.rate_memory = AsyncMock(return_value=True)
    manager.delete_memory = AsyncMock(return_value=1)
    manager.delete_rule = AsyncMock(return_value=True)
    manager.update_memory = AsyncMock()
    manager.correct_memory = AsyncMock()
    manager.list_memories = AsyncMock(return_value=[])
    manager.count_memories = AsyncMock(return_value=0)
    manager.config = AsyncMock()
    manager.config.semantic_collection = "semantic"
    manager.config.episodic_collection = "episodic"
    return manager


@pytest.fixture
def mcp_server(mock_manager):
    """Create a MemoryMCPServer with mocked manager."""
    return MemoryMCPServer(mock_manager, server_name="test-memory")


def _get_tool_fn(server: MemoryMCPServer, name: str):
    for t in server.mcp._tool_manager.list_tools():
        if t.name == name:
            return t.fn
    raise ValueError(f"Tool {name} not found")


def _make_search_result(content: str = "test content", score: float = 0.9) -> MemorySearchResult:
    mem = SemanticMemory(content=content)
    return MemorySearchResult(memory=mem, score=score, memory_type=MemoryType.SEMANTIC)


class TestMemoryMCPServerInit:
    def test_init_creates_fastmcp(self, mcp_server):
        assert mcp_server.mcp is not None
        assert mcp_server.mcp.name == "test-memory"

    def test_custom_server_name(self, mock_manager):
        server = MemoryMCPServer(mock_manager, server_name="custom-name")
        assert server.mcp.name == "custom-name"

    def test_tools_registered(self, mcp_server):
        tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
        assert "memory_recall" in tool_names
        assert "memory_list" in tool_names
        assert "memory_store" in tool_names
        assert "memory_manage" in tool_names
        assert len(tool_names) == 4

    def test_get_streamable_http_app_returns_starlette(self, mcp_server):
        from starlette.applications import Starlette
        app = mcp_server.get_streamable_http_app()
        assert isinstance(app, Starlette)


class TestMemoryListTool:
    @pytest.mark.asyncio
    async def test_list_overview_empty(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 0
        result = await _get_tool_fn(mcp_server, "memory_list")()
        assert "Memory Overview" in result
        assert "Total memories: 0" in result
        assert "(empty)" in result

    @pytest.mark.asyncio
    async def test_list_overview_with_data(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 5
        mock_manager.list_memories.return_value = [
            SemanticMemory(id="s1", content="User prefers Python"),
            SemanticMemory(id="s2", content="Project uses FastAPI"),
        ]
        result = await _get_tool_fn(mcp_server, "memory_list")()
        assert "Memory Overview" in result
        assert "s1" in result
        assert "User prefers Python" in result
        assert "... and" in result

    @pytest.mark.asyncio
    async def test_list_overview_includes_drift_defense(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 0
        result = await _get_tool_fn(mcp_server, "memory_list")()
        assert "verify they still exist" in result

    @pytest.mark.asyncio
    async def test_list_category_knowledge(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 2
        mock_manager.list_memories.return_value = [
            SemanticMemory(id="s1", content="fact one"),
            SemanticMemory(id="s2", content="fact two"),
        ]
        result = await _get_tool_fn(mcp_server, "memory_list")(category="knowledge")
        assert "knowledge" in result
        assert "page 1/1" in result
        assert "2 total" in result
        assert "s1" in result
        assert "s2" in result

    @pytest.mark.asyncio
    async def test_list_category_pagination(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 30
        mock_manager.list_memories.return_value = [
            SemanticMemory(id=f"s{i}", content=f"fact {i}") for i in range(20)
        ]
        result = await _get_tool_fn(mcp_server, "memory_list")(category="knowledge", page=1, page_size=20)
        assert "page 1/2" in result
        assert "30 total" in result
        assert 'page=2' in result

    @pytest.mark.asyncio
    async def test_list_category_page_beyond(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 5
        result = await _get_tool_fn(mcp_server, "memory_list")(category="knowledge", page=10)
        assert "beyond" in result

    @pytest.mark.asyncio
    async def test_list_invalid_category(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_list")(category="invalid")
        assert "Error" in result
        assert "invalid" in result

    @pytest.mark.asyncio
    async def test_list_clamps_page_size(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 1
        mock_manager.list_memories.return_value = [SemanticMemory(id="s1", content="test")]
        await _get_tool_fn(mcp_server, "memory_list")(category="knowledge", page_size=100)
        call_kwargs = mock_manager.list_memories.call_args[1]
        assert call_kwargs["limit"] == 50

    @pytest.mark.asyncio
    async def test_list_clamps_page_size_min(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 1
        mock_manager.list_memories.return_value = [SemanticMemory(id="s1", content="test")]
        await _get_tool_fn(mcp_server, "memory_list")(category="knowledge", page_size=0)
        call_kwargs = mock_manager.list_memories.call_args[1]
        assert call_kwargs["limit"] == 1

    @pytest.mark.asyncio
    async def test_list_overview_skips_instruction(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 0
        result = await _get_tool_fn(mcp_server, "memory_list")()
        assert "instruction" not in result.lower().split("## ")[-1] if "## " in result else True

    @pytest.mark.asyncio
    async def test_list_category_empty(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 0
        mock_manager.list_memories.return_value = []
        result = await _get_tool_fn(mcp_server, "memory_list")(category="event")
        assert "event" in result
        assert "0 total" in result

    @pytest.mark.asyncio
    async def test_list_category_include_archived(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 1
        mock_manager.list_memories.return_value = [SemanticMemory(id="s1", content="archived item")]
        await _get_tool_fn(mcp_server, "memory_list")(
            category="knowledge", include_archived=True
        )
        call_kwargs = mock_manager.list_memories.call_args[1]
        assert call_kwargs["include_archived"] is True

    @pytest.mark.asyncio
    async def test_list_category_budget_truncation(self, mcp_server, mock_manager):
        mock_manager.count_memories.return_value = 3
        huge_content = "x" * 20000
        mock_manager.list_memories.return_value = [
            SemanticMemory(id=f"s{i}", content=huge_content) for i in range(3)
        ]
        result = await _get_tool_fn(mcp_server, "memory_list")(
            category="knowledge", page_size=3
        )
        assert "list_budget" in result or "s0" in result


class TestMemoryRecallTool:
    @pytest.mark.asyncio
    async def test_recall_no_results(self, mcp_server, mock_manager):
        mock_manager.search.return_value = []
        result = await _get_tool_fn(mcp_server, "memory_recall")(query="test query")
        assert result == "No relevant memories found."

    @pytest.mark.asyncio
    async def test_recall_with_results(self, mcp_server, mock_manager):
        mock_manager.search.return_value = [_make_search_result("User prefers dark mode", 0.95)]
        result = await _get_tool_fn(mcp_server, "memory_recall")(query="preferences")
        assert "User prefers dark mode" in result
        assert "0.95" in result

    @pytest.mark.asyncio
    async def test_recall_includes_drift_defense(self, mcp_server, mock_manager):
        mock_manager.search.return_value = [_make_search_result()]
        result = await _get_tool_fn(mcp_server, "memory_recall")(query="test")
        assert "verify they still exist" in result

    @pytest.mark.asyncio
    async def test_recall_with_categories_filter(self, mcp_server, mock_manager):
        mock_manager.search.return_value = []
        await _get_tool_fn(mcp_server, "memory_recall")(query="test", categories="knowledge,event")
        call_kwargs = mock_manager.search.call_args[1]
        assert call_kwargs["memory_types"] == [MemoryType.SEMANTIC, MemoryType.EPISODIC]

    @pytest.mark.asyncio
    async def test_recall_with_profile_key(self, mcp_server, mock_manager):
        mock_manager.get_profile_attribute.return_value = "pytest"
        result = await _get_tool_fn(mcp_server, "memory_recall")(
            query="ignored", profile_key="testing_framework"
        )
        assert result == "testing_framework: pytest"
        mock_manager.get_profile_attribute.assert_called_once_with("testing_framework")

    @pytest.mark.asyncio
    async def test_recall_profile_key_not_found(self, mcp_server, mock_manager):
        mock_manager.get_profile_attribute.return_value = None
        result = await _get_tool_fn(mcp_server, "memory_recall")(
            query="ignored", profile_key="nonexistent"
        )
        assert "No profile attribute" in result

    @pytest.mark.asyncio
    async def test_recall_profile_disabled(self, mcp_server, mock_manager):
        mock_manager.has_relational = False
        result = await _get_tool_fn(mcp_server, "memory_recall")(
            query="ignored", profile_key="name"
        )
        assert "not enabled" in result

    @pytest.mark.asyncio
    async def test_recall_with_since(self, mcp_server, mock_manager):
        mock_manager.search.return_value = []
        await _get_tool_fn(mcp_server, "memory_recall")(query="test", since="7d")
        call_kwargs = mock_manager.search.call_args[1]
        assert call_kwargs["since"] is not None

    @pytest.mark.asyncio
    async def test_recall_clamps_limit(self, mcp_server, mock_manager):
        mock_manager.search.return_value = []
        await _get_tool_fn(mcp_server, "memory_recall")(query="test", limit=100)
        call_kwargs = mock_manager.search.call_args[1]
        assert call_kwargs["limit"] == 15


class TestMemoryStoreTool:
    @pytest.mark.asyncio
    async def test_store_knowledge(self, mcp_server, mock_manager):
        stored = SemanticMemory(id="mem-1", content="Test fact")
        mock_manager.add_knowledge.return_value = stored
        result = await _get_tool_fn(mcp_server, "memory_store")(content="Test fact")
        assert "stored" in result
        assert "mem-1" in result

    @pytest.mark.asyncio
    async def test_store_empty_content(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_store")(content="   ")
        assert "Error" in result
        assert "empty" in result

    @pytest.mark.asyncio
    async def test_store_invalid_category(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_store")(content="test", category="invalid")
        assert "Error" in result
        assert "invalid" in result

    @pytest.mark.asyncio
    async def test_store_preference_requires_key(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_store")(
            content="dark mode", category="preference"
        )
        assert "preference_key" in result

    @pytest.mark.asyncio
    async def test_store_preference_with_key(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_store")(
            content="dark mode", category="preference", preference_key="theme"
        )
        assert "theme" in result
        mock_manager.set_profile_attribute.assert_called_once_with("theme", "dark mode")

    @pytest.mark.asyncio
    async def test_store_rule_requires_trigger(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_store")(
            content="use async", category="rule"
        )
        assert "rule_trigger" in result

    @pytest.mark.asyncio
    async def test_store_rule_with_trigger(self, mcp_server, mock_manager):
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory
        stored = ProceduralMemory(
            id="rule-1", content="use async", trigger="python tool", action="use async"
        )
        mock_manager.add_rule.return_value = stored
        result = await _get_tool_fn(mcp_server, "memory_store")(
            content="use async", category="rule", rule_trigger="python tool"
        )
        assert "stored" in result
        assert "rule-1" in result

    @pytest.mark.asyncio
    async def test_store_event(self, mcp_server, mock_manager):
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory
        stored = EpisodicMemory(id="evt-1", content="deployed v2")
        mock_manager.add_event.return_value = stored
        result = await _get_tool_fn(mcp_server, "memory_store")(
            content="deployed v2", category="event"
        )
        assert "stored" in result
        assert "evt-1" in result

    @pytest.mark.asyncio
    async def test_store_instruction(self, mcp_server, mock_manager):
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory
        stored = ProceduralMemory(
            id="inst-1", content="always lint", trigger="always", action="always lint"
        )
        mock_manager.add_rule.return_value = stored
        result = await _get_tool_fn(mcp_server, "memory_store")(
            content="always lint", category="instruction"
        )
        assert "stored" in result
        assert "inst-1" in result

    @pytest.mark.asyncio
    async def test_store_invalid_write_target(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_store")(
            content="test", write_target="invalid"
        )
        assert "Error" in result


class TestMemoryManageTool:
    @pytest.mark.asyncio
    async def test_manage_rate(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_manage")(
            action="rate", memory_id="m1", category="knowledge", rating_score=5
        )
        assert "rated" in result
        mock_manager.rate_memory.assert_called_once_with("m1", 5)

    @pytest.mark.asyncio
    async def test_manage_rate_missing_score(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_manage")(
            action="rate", memory_id="m1", category="knowledge"
        )
        assert "rating_score" in result

    @pytest.mark.asyncio
    async def test_manage_delete_knowledge(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_manage")(
            action="delete", memory_id="m1", category="knowledge"
        )
        assert "deleted" in result
        mock_manager.delete_memory.assert_called_once_with("semantic", ["m1"])

    @pytest.mark.asyncio
    async def test_manage_delete_rule(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_manage")(
            action="delete", memory_id="r1", category="rule"
        )
        assert "deleted" in result
        mock_manager.delete_rule.assert_called_once_with("r1")

    @pytest.mark.asyncio
    async def test_manage_update(self, mcp_server, mock_manager):
        updated = SemanticMemory(id="m1", content="updated content")
        mock_manager.update_memory.return_value = updated
        result = await _get_tool_fn(mcp_server, "memory_manage")(
            action="update", memory_id="m1", category="knowledge", new_content="updated content"
        )
        assert "updated" in result

    @pytest.mark.asyncio
    async def test_manage_update_missing_content(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_manage")(
            action="update", memory_id="m1", category="knowledge"
        )
        assert "new_content" in result

    @pytest.mark.asyncio
    async def test_manage_correct(self, mcp_server, mock_manager):
        correction = SemanticMemory(id="c1", content="corrected fact")
        mock_manager.correct_memory.return_value = correction
        result = await _get_tool_fn(mcp_server, "memory_manage")(
            action="correct", memory_id="m1", category="knowledge", new_content="corrected fact"
        )
        assert "corrected" in result
        assert "c1" in result

    @pytest.mark.asyncio
    async def test_manage_invalid_action(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_manage")(
            action="invalid", memory_id="m1", category="knowledge"
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_manage_invalid_category(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_manage")(
            action="delete", memory_id="m1", category="invalid"
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_manage_claim_rejected(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_manage")(
            action="delete", memory_id="c1", category="claim"
        )
        assert "Error" in result
        assert "claim" in result

    @pytest.mark.asyncio
    async def test_manage_delete_profile_rejected(self, mcp_server, mock_manager):
        result = await _get_tool_fn(mcp_server, "memory_manage")(
            action="delete", memory_id="p1", category="preference"
        )
        assert "cannot be deleted" in result


class TestFactoryFunction:
    def test_factory_creates_server(self, mock_manager):
        server = create_memory_mcp_server(mock_manager, server_name="factory-test")
        assert isinstance(server, MemoryMCPServer)
        assert server.mcp.name == "factory-test"

    def test_factory_default_name(self, mock_manager):
        server = create_memory_mcp_server(mock_manager)
        assert server.mcp.name == "myrm-memory"
