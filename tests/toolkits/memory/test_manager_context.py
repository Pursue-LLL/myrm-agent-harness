"""Tests for MemoryManager context loading and convenience methods."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError, MemoryNotFoundError
from myrm_agent_harness.toolkits.memory.config import AgentMemoryPolicy, MemoryScopeLevel, MemoryWritePolicy
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, ProceduralMemory, RuleSource, SemanticMemory


class TestContextLoading:
    """Test get_context operation."""

    @pytest.mark.asyncio
    async def test_get_context_with_all_components(self, mock_relational_store, memory_config):
        """Test get_context includes all requested components."""
        mock_relational_store.list_profiles.return_value = [("key1", "value1")]
        mock_relational_store.list_rules.return_value = []

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        context = await manager.get_context(include_profile=True, include_rules=True, include_agent_instructions=True)

        assert "global_profile" in context
        assert "peer_profile" in context
        assert "rules" in context
        assert mock_relational_store.list_profiles.await_args.kwargs["namespaces"] == ["global", "agent:default"]
        assert mock_relational_store.list_rules.await_args.kwargs["namespaces"] == ["global", "agent:default"]

    @pytest.mark.asyncio
    async def test_get_context_without_relational(self, mock_vector_store, mock_embedding, memory_config):
        """Test get_context returns default structure when no relational backend."""
        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        context = await manager.get_context()

        assert "global_profile" in context
        assert "peer_profile" in context
        assert "rules" in context
        assert context["global_profile"] == {}
        assert context["peer_profile"] == {}
        assert context["rules"] == []

    @pytest.mark.asyncio
    async def test_get_learned_context_uses_policy_namespaces_and_budget(
        self, mock_relational_store, mock_vector_store, memory_config
    ):
        mock_relational_store.list_rules.return_value = [
            ProceduralMemory(
                id="rule-1",
                content="When: review -> Do: be strict",
                trigger="review",
                action="be strict",
                priority=10,
                source=RuleSource.AGENT_SELF,
            )
        ]
        mock_vector_store.scroll.return_value = [
            VectorDocument(
                id="pref-1",
                content="User prefers concise answers",
                vector=[0.1] * 8,
                metadata={
                    "memory_type": "semantic",
                    "importance": 1.0,
                    "confidence": 1.0,
                    "access_count": 0,
                    "preference_type": "explicit",
                    "preference_strength": 1.0,
                    "namespaces": ["global"],
                    "primary_namespace": "global",
                    "source_chat_id": "",
                    "correction_of": "",
                },
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        ]
        config = replace(memory_config, max_learned_context_chars=200)

        manager = MemoryManager(
            config,
            user_id="test_user",
            relational=mock_relational_store,
            vector=mock_vector_store,
            memory_policy=AgentMemoryPolicy(
                agent_id="planner",
                channel_id="telegram",
                task_id="task-1",
                read_scopes=(MemoryScopeLevel.GLOBAL),
                write_policy=MemoryWritePolicy.TASK,
            ),
        )

        context = await manager.get_learned_context()

        # The created_at field is dynamically generated during the test, so we pop it before asserting
        assert len(context["learned_rules"]) == 1
        rule_dict = context["learned_rules"][0]
        assert "created_at" in rule_dict
        rule_dict.pop("created_at")
        assert rule_dict == {"id": "rule-1", "trigger": "review", "action": "be strict", "tool_rule_priority": "normal"}
        # Check preferences
        assert len(context["learned_preferences"]) == 1
        pref_dict = context["learned_preferences"][0]
        assert "created_at" in pref_dict
        pref_dict.pop("created_at")
        assert pref_dict == {"id": "pref-1", "content": "User prefers concise answers", "type": "explicit"}
        assert mock_relational_store.list_rules.await_args.kwargs["namespaces"] == ["global"]
        assert mock_vector_store.scroll.await_args.kwargs["filters"]["primary_namespace"] == ["global"]

    @pytest.mark.asyncio
    async def test_get_learned_context_with_preference_strategy(
        self, mock_relational_store, mock_vector_store, memory_config
    ):
        """get_learned_context uses PreferenceStabilityStrategy when provided."""
        from myrm_agent_harness.toolkits.memory.strategies.preference_stability import (
            CueFamily,
            PreferenceFacet,
            PreferenceLifecycle,
        )

        mock_relational_store.list_rules.return_value = []
        facet = PreferenceFacet(
            id="facet-1",
            key="reply_style",
            value="concise",
            cue=CueFamily.EXPLICIT,
            lifecycle=PreferenceLifecycle.ACTIVE,
            stability=1.0,
        )
        strategy = AsyncMock()
        strategy.get_active_preferences.return_value = [facet]

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            relational=mock_relational_store,
            vector=mock_vector_store,
            preference_facet_store=AsyncMock(),
        )
        manager._preference_strategy = strategy

        context = await manager.get_learned_context()

        assert len(context["learned_preferences"]) == 1
        pref = context["learned_preferences"][0]
        assert pref["content"] == "concise"
        assert pref["type"] == "explicit"
        strategy.get_active_preferences.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_learned_context_handles_rules_query_error(
        self, mock_relational_store, mock_vector_store, memory_config
    ):
        """get_learned_context tolerates relational query failures."""
        mock_relational_store.list_rules.side_effect = Exception("db down")
        mock_vector_store.scroll.return_value = ([], None)

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            relational=mock_relational_store,
            vector=mock_vector_store,
        )

        context = await manager.get_learned_context()
        assert context["learned_rules"] == []
        assert context["learned_preferences"] == []

    @pytest.mark.asyncio
    async def test_get_learned_context_respects_budget(
        self, mock_relational_store, mock_vector_store, memory_config
    ):
        """get_learned_context truncates rules to the configured budget."""
        from myrm_agent_harness.toolkits.memory.types import RuleSource

        mock_relational_store.list_rules.return_value = [
            ProceduralMemory(
                id=f"rule-{i}",
                content=f"When: trigger {i} -> Do: action {i}",
                trigger=f"trigger {i}",
                action=f"action {i}",
                priority=10 - i,
                source=RuleSource.AGENT_SELF,
            )
            for i in range(10)
        ]
        mock_vector_store.scroll.return_value = ([], None)
        config = replace(memory_config, max_learned_context_chars=60)

        manager = MemoryManager(
            config,
            user_id="test_user",
            relational=mock_relational_store,
            vector=mock_vector_store,
        )

        context = await manager.get_learned_context()
        # Budget 60 chars truncates the rule list.
        assert 0 < len(context["learned_rules"]) < 10

    @pytest.mark.asyncio
    async def test_get_learned_context_normal_prefs_and_corrections(
        self, mock_relational_store, mock_vector_store, memory_config
    ):
        """get_learned_context separates corrections from normal preferences."""
        mock_relational_store.list_rules.return_value = []
        mock_vector_store.scroll.return_value = (
            [
                VectorDocument(
                    id="corr-1",
                    content="User prefers X not Y",
                    vector=[0.1] * 8,
                    metadata={
                        "memory_type": "semantic",
                        "importance": 1.0,
                        "confidence": 1.0,
                        "access_count": 0,
                        "preference_type": "explicit",
                        "preference_strength": 1.0,
                        "correction_of": "old-mem",
                        "source_error": "was wrong",
                        "namespaces": ["global"],
                        "primary_namespace": "global",
                        "source_chat_id": "",
                    },
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                VectorDocument(
                    id="norm-1",
                    content="User prefers concise",
                    vector=[0.1] * 8,
                    metadata={
                        "memory_type": "semantic",
                        "importance": 0.8,
                        "confidence": 1.0,
                        "access_count": 0,
                        "preference_type": "implicit",
                        "preference_strength": 0.6,
                        "correction_of": "",
                        "source_error": "",
                        "namespaces": ["global"],
                        "primary_namespace": "global",
                        "source_chat_id": "",
                    },
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
            ],
            None,
        )

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            relational=mock_relational_store,
            vector=mock_vector_store,
        )

        context = await manager.get_learned_context()

        prefs = context["learned_preferences"]
        assert len(prefs) == 2
        corr = next(p for p in prefs if p["id"] == "corr-1")
        assert corr["source_error"] == "was wrong"
        norm = next(p for p in prefs if p["id"] == "norm-1")
        assert "source_error" not in norm


class TestConvenienceMethods:
    """Test convenience methods like add_knowledge, add_event, add_rule."""

    @pytest.mark.asyncio
    async def test_add_knowledge(self, mock_vector_store, mock_embedding, memory_config):
        """Test add_knowledge convenience method."""
        mock_vector_store.upsert.return_value = ["mem-1"]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        result = await manager.add_knowledge("Python is a programming language", importance=0.8, tags=["programming"])

        assert isinstance(result, SemanticMemory)
        assert result.content == "Python is a programming language"
        assert result.importance == 0.8

    @pytest.mark.asyncio
    async def test_add_event(self, mock_vector_store, mock_embedding, memory_config):
        """Test add_event convenience method."""
        mock_vector_store.upsert.return_value = ["mem-2"]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        result = await manager.add_event("User asked about Python", event_type="question", related_entities=["Python"])

        assert isinstance(result, EpisodicMemory)
        assert result.content == "User asked about Python"
        assert result.event_type == "question"

    @pytest.mark.asyncio
    async def test_add_rule(self, mock_relational_store, memory_config):
        """Test add_rule convenience method."""
        rule_obj = ProceduralMemory(
            id="rule-1", content="When: trigger → Do: action", trigger="trigger", action="action"
        )
        mock_relational_store.create_rule.return_value = rule_obj

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        result = await manager.add_rule(trigger="user asks weather", action="call weather_api", priority=1)

        assert isinstance(result, ProceduralMemory)
        assert result.id == "rule-1"


class TestCorrectMemory:
    """Test memory correction workflow."""

    @pytest.mark.asyncio
    async def test_correct_semantic_memory(self, mock_vector_store, mock_embedding, memory_config):
        """Test correcting a factually wrong semantic memory."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

        existing_doc = VectorDocument(
            id="mem-1",
            content="Paris is the capital of Germany",
            vector=[0.1] * 768,
            metadata={
                "memory_type": "semantic",
                "importance": 0.7,
                "confidence": 1.0,
                "source_chat_id": "",
                "preference_type": "",
                "preference_strength": 0.0,
                "correction_of": "",
                "access_count": 5,
            },
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_vector_store.get.return_value = [existing_doc]
        mock_vector_store.upsert.return_value = ["mem-new"]

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        correction = await manager.correct_memory("mem-1", "Paris is the capital of France")

        assert isinstance(correction, SemanticMemory)
        assert correction.content == "Paris is the capital of France"
        assert correction.correction_of == "mem-1"
        assert correction.importance > 0.7
        assert mock_vector_store.upsert.call_count == 2

    @pytest.mark.asyncio
    async def test_correct_nonexistent_memory_raises_error(self, mock_vector_store, mock_embedding, memory_config):
        """Test correcting non-existent memory raises error."""
        mock_vector_store.get.return_value = None

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        with pytest.raises(MemoryNotFoundError, match="Memory mem-1 not found"):
            await manager.correct_memory("mem-1", "Corrected content")

    @pytest.mark.asyncio
    async def test_correct_non_semantic_raises_error(self, mock_relational_store, memory_config):
        """Test correcting non-semantic memory raises error."""
        rule = ProceduralMemory(id="rule-1", content="Test rule", trigger="trigger", action="action")
        mock_relational_store.get_rule.return_value = rule

        manager = MemoryManager(memory_config, user_id="test_user", relational=mock_relational_store)

        with pytest.raises(MemoryError, match="Correction only supports SemanticMemory"):
            await manager.correct_memory("rule-1", "Corrected")


class TestLearnedContextExtraBranches:
    """Cover the remaining get_learned_context branches in retrieval_write.py."""

    @pytest.mark.asyncio
    async def test_rule_tool_metadata_included(
        self, mock_relational_store, mock_vector_store, memory_config
    ):
        """Rules with tool_name / tool_rule_priority / reasoning / application surface in context."""
        from myrm_agent_harness.toolkits.memory.types import ToolRulePriority

        mock_relational_store.list_rules.return_value = [
            ProceduralMemory(
                id="tool-rule",
                content="When: use browser -> Do: prefer chromium",
                trigger="use browser",
                action="prefer chromium",
                priority=8,
                source=RuleSource.AGENT_SELF,
                reasoning="browser is more stable",
                application="only for web tasks",
                tool_name="browser",
                tool_rule_priority=ToolRulePriority.HIGH,
            )
        ]
        mock_vector_store.scroll.return_value = ([], None)

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            relational=mock_relational_store,
            vector=mock_vector_store,
        )

        context = await manager.get_learned_context()
        rule = context["learned_rules"][0]
        assert rule["reasoning"] == "browser is more stable"
        assert rule["application"] == "only for web tasks"
        assert rule["tool_name"] == "browser"
        assert rule["tool_rule_priority"] == "high"

    @pytest.mark.asyncio
    async def test_model_context_tokens_scales_budget(
        self, mock_relational_store, mock_vector_store, memory_config
    ):
        """model_context_tokens lifts the budget above base chars."""
        mock_relational_store.list_rules.return_value = [
            ProceduralMemory(
                id=f"r{i}",
                content=f"When: trigger {i} -> Do: action {i}",
                trigger=f"trigger {i}",
                action=f"action {i}",
                priority=10 - i,
                source=RuleSource.AGENT_SELF,
            )
            for i in range(15)
        ]
        mock_vector_store.scroll.return_value = ([], None)
        config = replace(
            memory_config, model_context_tokens=6000, max_learned_context_chars=50
        )

        manager = MemoryManager(
            config,
            user_id="test_user",
            relational=mock_relational_store,
            vector=mock_vector_store,
        )

        context = await manager.get_learned_context()
        # budget = max(50, 6000//30=200) = 200, well above the base 50 that
        # would fit only ~1 rule, so several rules are included.
        assert len(context["learned_rules"]) > 1

    @pytest.mark.asyncio
    async def test_non_preference_docs_skipped(
        self, mock_relational_store, mock_vector_store, memory_config
    ):
        """Docs without a valid preference_type / strength are ignored."""
        mock_relational_store.list_rules.return_value = []
        mock_vector_store.scroll.return_value = (
            [
                VectorDocument(
                    id="plain-1",
                    content="Just a fact",
                    vector=[0.1] * 8,
                    metadata={
                        "memory_type": "semantic",
                        "importance": 0.5,
                        "confidence": 1.0,
                        "access_count": 0,
                        "preference_type": "",
                        "preference_strength": 0.0,
                        "namespaces": ["global"],
                        "primary_namespace": "global",
                        "source_chat_id": "",
                    },
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                VectorDocument(
                    id="bad-strength",
                    content="Bad strength",
                    vector=[0.1] * 8,
                    metadata={
                        "memory_type": "semantic",
                        "importance": 0.5,
                        "confidence": 1.0,
                        "access_count": 0,
                        "preference_type": "implicit",
                        "preference_strength": "not-a-number",
                        "namespaces": ["global"],
                        "primary_namespace": "global",
                        "source_chat_id": "",
                    },
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
            ],
            None,
        )

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            relational=mock_relational_store,
            vector=mock_vector_store,
        )

        context = await manager.get_learned_context()
        assert context["learned_preferences"] == []
