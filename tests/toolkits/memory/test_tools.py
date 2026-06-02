"""Tests for memory tools formatting, provenance labels, and RecallMode visibility."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.config import RecallMode
from myrm_agent_harness.toolkits.memory.memory_agent_tools import (
    _channel_label,
    _is_stale,
    create_memory_tools,
    memory_age_label,
)
from myrm_agent_harness.toolkits.memory.types import (
    ClaimMemory,
    EpisodicMemory,
    MemoryScope,
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)


@pytest.mark.asyncio
async def test_memory_recall_formats_channel_provenance(mock_vector_store, mock_embedding, memory_config):
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, channel_id="telegram"
    )
    with patch.object(
        MemoryManager,
        "search",
        AsyncMock(
            return_value=[
                MemorySearchResult(
                    memory=SemanticMemory(
                        content="Discussed deployment preference",
                        scope=MemoryScope(
                            primary_namespace="channel:feishu",
                            namespaces=["global", "channel:feishu"],
                            channel_id="feishu",
                        ),
                    ),
                    score=0.88,
                    memory_type=MemoryType.SEMANTIC,
                )
            ]
        ),
    ):
        recall_tool = next(tool for tool in create_memory_tools(manager) if tool.name == "memory_recall_tool")
        result = await recall_tool.ainvoke({"query": "deployment"})

    assert "[from Feishu] [knowledge]" in result
    assert "Discussed deployment preference" in result


@pytest.mark.asyncio
async def test_memory_recall_formats_claim_graph_annotations(mock_vector_store, mock_embedding, memory_config):
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, channel_id="telegram"
    )
    with patch.object(
        MemoryManager,
        "search",
        AsyncMock(
            return_value=[
                MemorySearchResult(
                    memory=ClaimMemory(
                        id="claim:auth-task",
                        content="Claim: Auth task | Add JWT authentication -> Failed rollout",
                        claim_key="auth-task",
                        title="Auth task",
                        claim_text="Add JWT authentication -> Failed rollout",
                        last_result="Failed rollout",
                        evidence_count=4,
                        freshness="fresh",
                        freshness_days=1,
                        contradiction_status="conflicted",
                        scope=MemoryScope(
                            primary_namespace="claim_graph:test_user",
                            namespaces=["global", "claim_graph:test_user"],
                            channel_id="telegram",
                        ),
                        metadata={
                            "latest_channel_id": "telegram",
                            "latest_relationship_type": "SUPERSEDED_BY",
                        },
                    ),
                    score=0.86,
                    memory_type=MemoryType.CLAIM,
                )
            ]
        ),
    ):
        recall_tool = next(tool for tool in create_memory_tools(manager) if tool.name == "memory_recall_tool")
        result = await recall_tool.ainvoke({"query": "jwt auth"})

    assert "[from Telegram] [claim]" in result
    assert "[claim_graph freshness=fresh contradiction=conflicted evidence=4 relation=superseded_by]" in result


class TestRecallModeToolVisibility:
    """RecallMode controls which tools are exposed to the agent."""

    def _make_manager(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        return MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

    def test_hybrid_exposes_all_tools(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        tools = create_memory_tools(manager, recall_mode=RecallMode.HYBRID)
        names = {t.name for t in tools}
        assert names == {"memory_recall_tool", "memory_save_tool", "memory_manage_tool"}

    def test_context_hides_all_tools(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        tools = create_memory_tools(manager, recall_mode=RecallMode.CONTEXT)
        assert tools == []

    def test_tools_mode_exposes_all_tools(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        tools = create_memory_tools(manager, recall_mode=RecallMode.TOOLS)
        names = {t.name for t in tools}
        assert names == {"memory_recall_tool", "memory_save_tool", "memory_manage_tool"}

    def test_default_is_hybrid(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        tools_default = create_memory_tools(manager)
        tools_hybrid = create_memory_tools(manager, recall_mode=RecallMode.HYBRID)
        assert len(tools_default) == len(tools_hybrid) == 3


# ── Utility function tests ──


class TestMemoryAgeLabel:
    def test_today(self):
        assert memory_age_label(datetime.now(UTC)) == "today"

    def test_yesterday(self):
        assert memory_age_label(datetime.now(UTC) - timedelta(days=1)) == "yesterday"

    def test_days_ago(self):
        assert memory_age_label(datetime.now(UTC) - timedelta(days=5)) == "5 days ago"

    def test_one_month(self):
        assert memory_age_label(datetime.now(UTC) - timedelta(days=35)) == "1 month ago"

    def test_months_ago(self):
        assert memory_age_label(datetime.now(UTC) - timedelta(days=90)) == "3 months ago"

    def test_one_year(self):
        assert memory_age_label(datetime.now(UTC) - timedelta(days=400)) == "1 year ago"

    def test_years_ago(self):
        assert memory_age_label(datetime.now(UTC) - timedelta(days=800)) == "2 years ago"


class TestIsStale:
    def test_fresh_memory_not_stale(self):
        assert not _is_stale(datetime.now(UTC))

    def test_old_memory_is_stale(self):
        assert _is_stale(datetime.now(UTC) - timedelta(hours=25))


class TestChannelLabel:
    def test_none_returns_empty(self):
        assert _channel_label(None) == ""

    def test_empty_returns_empty(self):
        assert _channel_label("") == ""

    def test_telegram_alias(self):
        assert _channel_label("telegram") == "[from Telegram] "

    def test_tg_alias(self):
        assert _channel_label("tg") == "[from Telegram] "

    def test_feishu_alias(self):
        assert _channel_label("feishu") == "[from Feishu] "

    def test_unknown_channel_title_case(self):
        assert _channel_label("my_custom_chan") == "[from My Custom Chan] "


# ── memory_recall tool tests ──


class TestMemoryRecallTool:
    def _make_manager(self, mock_vector_store, mock_embedding, memory_config, **kw):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        return MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, **kw)

    @pytest.mark.asyncio
    async def test_recall_no_results(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(type(manager), "search", AsyncMock(return_value=[])):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_recall_tool")
            result = await tool.ainvoke({"query": "nothing"})
        assert "No relevant memories found" in result

    @pytest.mark.asyncio
    async def test_recall_profile_key(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        with patch.object(MemoryManager, "get_profile_attribute", AsyncMock(return_value="Alice")):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_recall_tool")
            result = await tool.ainvoke({"query": "", "profile_key": "name"})
        assert "name: Alice" in result

    @pytest.mark.asyncio
    async def test_recall_profile_key_not_found(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        with patch.object(MemoryManager, "get_profile_attribute", AsyncMock(return_value=None)):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_recall_tool")
            result = await tool.ainvoke({"query": "", "profile_key": "missing_key"})
        assert "No profile attribute" in result

    @pytest.mark.asyncio
    async def test_recall_profile_key_no_relational(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_recall_tool")
        result = await tool.ainvoke({"query": "", "profile_key": "name"})
        assert "not enabled" in result.lower()

    @pytest.mark.asyncio
    async def test_recall_stale_warning(self, mock_vector_store, mock_embedding, memory_config):
        stale_time = datetime.now(UTC) - timedelta(hours=48)
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(
            type(manager),
            "search",
            AsyncMock(
                return_value=[
                    MemorySearchResult(
                        memory=SemanticMemory(content="old fact", created_at=stale_time),
                        score=0.9,
                        memory_type=MemoryType.SEMANTIC,
                    )
                ]
            ),
        ):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_recall_tool")
            result = await tool.ainvoke({"query": "fact"})
        assert "may be outdated" in result

    @pytest.mark.asyncio
    async def test_recall_source_error_annotation(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(
            type(manager),
            "search",
            AsyncMock(
                return_value=[
                    MemorySearchResult(
                        memory=SemanticMemory(content="corrected pref", source_error="wrong output"),
                        score=0.85,
                        memory_type=MemoryType.SEMANTIC,
                    )
                ]
            ),
        ):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_recall_tool")
            result = await tool.ainvoke({"query": "pref"})
        assert "(avoid: wrong output)" in result

    @pytest.mark.asyncio
    async def test_recall_drift_defense_footer(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(
            type(manager),
            "search",
            AsyncMock(
                return_value=[
                    MemorySearchResult(
                        memory=SemanticMemory(content="some fact"), score=0.9, memory_type=MemoryType.SEMANTIC
                    )
                ]
            ),
        ):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_recall_tool")
            result = await tool.ainvoke({"query": "fact"})
        assert "verify they still exist" in result

    @pytest.mark.asyncio
    async def test_recall_categories_filter(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        search_mock = AsyncMock(return_value=[])
        with patch.object(MemoryManager, "search", search_mock):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_recall_tool")
            await tool.ainvoke({"query": "test", "categories": ["knowledge", "event"]})
        call_kw = search_mock.call_args
        types = call_kw.kwargs.get("memory_types") or call_kw[1].get("memory_types")
        assert MemoryType.SEMANTIC in types
        assert MemoryType.EPISODIC in types


# ── memory_save tool tests ──


class TestMemorySaveTool:
    def _make_manager(self, mock_vector_store, mock_embedding, memory_config, **kw):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        return MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, **kw)

    @pytest.mark.asyncio
    async def test_save_knowledge(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(
            MemoryManager, "add_knowledge", AsyncMock(return_value=SemanticMemory(content="fact", id="mem-1"))
        ):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
            result = await tool.ainvoke({"content": "fact", "category": "knowledge"})
        assert "stored" in result
        assert "mem-1" in result

    @pytest.mark.asyncio
    async def test_save_event(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(
            MemoryManager, "add_event", AsyncMock(return_value=EpisodicMemory(content="event", id="ev-1"))
        ):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
            result = await tool.ainvoke({"content": "event", "category": "event"})
        assert "stored" in result

    @pytest.mark.asyncio
    async def test_save_preference_requires_key(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
        result = await tool.ainvoke({"content": "Python", "category": "preference"})
        assert "preference_key" in result.lower()

    @pytest.mark.asyncio
    async def test_save_preference_with_key(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        with patch.object(MemoryManager, "set_profile_attribute", AsyncMock(return_value=None)):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
            result = await tool.ainvoke(
                {
                    "content": "Python",
                    "category": "preference",
                    "preference_key": "language",
                }
            )
        assert "language" in result

    @pytest.mark.asyncio
    async def test_save_rule_requires_trigger(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
        result = await tool.ainvoke({"content": "do X", "category": "rule"})
        assert "rule_trigger" in result.lower()

    @pytest.mark.asyncio
    async def test_save_instruction(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        with patch.object(
            MemoryManager,
            "add_rule",
            AsyncMock(
                return_value=ProceduralMemory(content="be concise", trigger="always", action="be concise", id="inst-1")
            ),
        ):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
            result = await tool.ainvoke({"content": "be concise", "category": "instruction"})
        assert "stored" in result.lower() or "instruction" in result.lower()

    @pytest.mark.asyncio
    async def test_save_knowledge_no_vector(self, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = MemoryManager(memory_config, user_id="test_user", relational=AsyncMock())
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
        result = await tool.ainvoke({"content": "fact", "category": "knowledge"})
        assert "not enabled" in result.lower()

    @pytest.mark.asyncio
    async def test_save_event_no_vector(self, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = MemoryManager(memory_config, user_id="test_user", relational=AsyncMock())
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
        result = await tool.ainvoke({"content": "ev", "category": "event"})
        assert "not enabled" in result.lower()

    @pytest.mark.asyncio
    async def test_save_rule_no_relational(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
        result = await tool.ainvoke(
            {
                "content": "action",
                "category": "rule",
                "rule_trigger": "when",
            }
        )
        assert "not enabled" in result.lower()

    @pytest.mark.asyncio
    async def test_save_exception_handling(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(MemoryManager, "add_knowledge", AsyncMock(side_effect=RuntimeError("db err"))):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
            result = await tool.ainvoke({"content": "fact", "category": "knowledge"})
        assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_save_rule_with_trigger(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        with patch.object(
            MemoryManager,
            "add_rule",
            AsyncMock(return_value=ProceduralMemory(content="do Y", trigger="when X", action="do Y", id="r-1")),
        ):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
            result = await tool.ainvoke(
                {
                    "content": "do Y",
                    "category": "rule",
                    "rule_trigger": "when X",
                }
            )
        assert "stored" in result.lower()

    @pytest.mark.asyncio
    async def test_save_preference_approval(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(
            mock_vector_store, mock_embedding, memory_config, relational=AsyncMock(), approval_required=True
        )
        with patch.object(MemoryManager, "set_profile_attribute", AsyncMock(return_value="pending-123")):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_save_tool")
            result = await tool.ainvoke(
                {
                    "content": "dark",
                    "category": "preference",
                    "preference_key": "theme",
                }
            )
        assert "approval" in result.lower()


# ── memory_manage tool tests ──


class TestMemoryManageTool:
    def _make_manager(self, mock_vector_store, mock_embedding, memory_config, **kw):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        return MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, **kw)

    @pytest.mark.asyncio
    async def test_manage_update(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        updated = SemanticMemory(content="new", id="mem-1")
        with patch.object(MemoryManager, "update_memory", AsyncMock(return_value=updated)):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
            result = await tool.ainvoke(
                {
                    "action": "update",
                    "memory_id": "mem-1",
                    "category": "knowledge",
                    "new_content": "new content",
                }
            )
        assert "updated" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_update_requires_content(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
        result = await tool.ainvoke(
            {
                "action": "update",
                "memory_id": "mem-1",
                "category": "knowledge",
            }
        )
        assert "new_content" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_delete_semantic(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(MemoryManager, "delete_memory", AsyncMock(return_value=1)):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
            result = await tool.ainvoke(
                {
                    "action": "delete",
                    "memory_id": "mem-1",
                    "category": "knowledge",
                }
            )
        assert "deleted" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_delete_rule(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        with patch.object(MemoryManager, "delete_rule", AsyncMock(return_value=True)):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
            result = await tool.ainvoke(
                {
                    "action": "delete",
                    "memory_id": "rule-1",
                    "category": "rule",
                }
            )
        assert "deleted" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_correct(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        correction = SemanticMemory(content="correct", id="cor-1")
        with patch.object(MemoryManager, "correct_memory", AsyncMock(return_value=correction)):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
            result = await tool.ainvoke(
                {
                    "action": "correct",
                    "memory_id": "mem-1",
                    "category": "knowledge",
                    "new_content": "correct fact",
                }
            )
        assert "corrected" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_correct_requires_content(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
        result = await tool.ainvoke(
            {
                "action": "correct",
                "memory_id": "mem-1",
                "category": "knowledge",
            }
        )
        assert "new_content" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_correct_only_knowledge(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
        result = await tool.ainvoke(
            {
                "action": "correct",
                "memory_id": "ev-1",
                "category": "event",
                "new_content": "fix",
            }
        )
        assert "only supported for knowledge" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_exception_handling(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(MemoryManager, "update_memory", AsyncMock(side_effect=RuntimeError("db error"))):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
            result = await tool.ainvoke(
                {
                    "action": "update",
                    "memory_id": "mem-1",
                    "category": "knowledge",
                    "new_content": "new",
                }
            )
        assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_delete_not_found(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(MemoryManager, "delete_memory", AsyncMock(return_value=0)):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
            result = await tool.ainvoke(
                {
                    "action": "delete",
                    "memory_id": "nonexistent",
                    "category": "knowledge",
                }
            )
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_delete_rule_not_found(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        with patch.object(MemoryManager, "delete_rule", AsyncMock(return_value=False)):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
            result = await tool.ainvoke(
                {
                    "action": "delete",
                    "memory_id": "nonexistent",
                    "category": "rule",
                }
            )
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_delete_profile_rejected(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
        result = await tool.ainvoke(
            {
                "action": "delete",
                "memory_id": "p-1",
                "category": "preference",
            }
        )
        assert "cannot be deleted" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_rate_memory(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(MemoryManager, "rate_memory", AsyncMock(return_value=True)):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
            result = await tool.ainvoke(
                {"action": "rate", "memory_id": "mem-1", "category": "knowledge", "rating_score": 5}
            )
        assert "rated" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_rate_requires_score(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
        result = await tool.ainvoke({"action": "rate", "memory_id": "mem-1", "category": "knowledge"})
        assert "rating_score" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_rate_only_knowledge_event(self, mock_vector_store, mock_embedding, memory_config):
        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config, relational=AsyncMock())
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
        result = await tool.ainvoke(
            {"action": "rate", "memory_id": "r-1", "category": "rule", "rating_score": 3}
        )
        assert "only supported" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_rate_not_found(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = self._make_manager(mock_vector_store, mock_embedding, memory_config)
        with patch.object(MemoryManager, "rate_memory", AsyncMock(return_value=False)):
            tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
            result = await tool.ainvoke(
                {"action": "rate", "memory_id": "nonexist", "category": "knowledge", "rating_score": 4}
            )
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_rate_no_vector(self, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = MemoryManager(memory_config, user_id="test_user", relational=AsyncMock())
        tool = next(t for t in create_memory_tools(manager) if t.name == "memory_manage_tool")
        result = await tool.ainvoke(
            {"action": "rate", "memory_id": "m-1", "category": "knowledge", "rating_score": 5}
        )
        assert "not enabled" in result.lower()


class TestParseStringList:
    """Tests for _parse_string_list helper."""

    def test_none_returns_empty(self):
        from myrm_agent_harness.toolkits.memory.memory_agent_tools import _parse_string_list

        assert _parse_string_list(None) == []

    def test_list_passthrough(self):
        from myrm_agent_harness.toolkits.memory.memory_agent_tools import _parse_string_list

        assert _parse_string_list(["a", "b"]) == ["a", "b"]

    def test_json_string_list(self):
        from myrm_agent_harness.toolkits.memory.memory_agent_tools import _parse_string_list

        assert _parse_string_list('["x", "y"]') == ["x", "y"]

    def test_comma_separated(self):
        from myrm_agent_harness.toolkits.memory.memory_agent_tools import _parse_string_list

        assert _parse_string_list("foo, bar, baz") == ["foo", "bar", "baz"]

    def test_invalid_json_falls_back_to_comma(self):
        from myrm_agent_harness.toolkits.memory.memory_agent_tools import _parse_string_list

        assert _parse_string_list("{not json}") == ["{not json}"]
