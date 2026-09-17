"""Tests for the user-endorsed (``is_user_locked``) rule write boundary.

Covers:
- ``update_memory`` applies an explicit ``is_user_locked`` so the WebUI toggle
  can both protect and release a rule
- ``update_memory`` leaves the lock untouched when the caller omits it
- The agent-surface guard identifies locked rules and rejects rewrites
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.agent_surface.rule_write_boundary import (
    get_user_locked_rule,
    rule_rewrite_protection_message,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory, SemanticMemory


class TestRuleWriteBoundaryGuard:
    def test_identifies_locked_procedural_rule(self) -> None:
        rule = ProceduralMemory(content="When: X → Do: Y", trigger="X", action="Y", is_user_locked=True)
        assert get_user_locked_rule(rule) is rule

    def test_ignores_unlocked_procedural_rule(self) -> None:
        rule = ProceduralMemory(content="When: X → Do: Y", trigger="X", action="Y", is_user_locked=False)
        assert get_user_locked_rule(rule) is None

    def test_ignores_vector_memory_even_when_pinned(self) -> None:
        """``pinned`` is not the rule lock; vector memories are never rule-locked."""
        memory = SemanticMemory(content="fact", pinned=True)
        assert get_user_locked_rule(memory) is None

    def test_ignores_missing_memory(self) -> None:
        assert get_user_locked_rule(None) is None

    def test_message_names_the_rule_and_the_way_out(self) -> None:
        message = rule_rewrite_protection_message("rule-42")
        assert "rule-42" in message
        assert "locked" in message
        assert "unlock" in message


class TestUpdateMemoryLockControl:
    @pytest.mark.asyncio
    async def test_explicit_true_protects_rule(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_relational_store: AsyncMock,
    ) -> None:
        rule = ProceduralMemory(content="When: X → Do: Y", trigger="X", action="Y", is_user_locked=False)
        mock_relational_store.get_rule.return_value = rule
        mock_relational_store.update_rule.side_effect = lambda _id, updated: updated

        mgr = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            relational=mock_relational_store,
            auto_warmup=False,
        )
        updated = await mgr.update_memory("r1", is_user_locked=True)
        assert updated.is_user_locked is True

    @pytest.mark.asyncio
    async def test_explicit_false_releases_rule(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_relational_store: AsyncMock,
    ) -> None:
        """Releasing must be possible; the WebUI toggle depends on it."""
        rule = ProceduralMemory(content="When: X → Do: Y", trigger="X", action="Y", is_user_locked=True)
        mock_relational_store.get_rule.return_value = rule
        mock_relational_store.update_rule.side_effect = lambda _id, updated: updated

        mgr = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            relational=mock_relational_store,
            auto_warmup=False,
        )
        updated = await mgr.update_memory("r1", is_user_locked=False)
        assert updated.is_user_locked is False

    @pytest.mark.asyncio
    async def test_release_and_edit_in_one_call(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_relational_store: AsyncMock,
    ) -> None:
        """The lock follows the explicit value even when content changes in the same call."""
        rule = ProceduralMemory(content="When: X → Do: Y", trigger="X", action="Y", is_user_locked=True)
        mock_relational_store.get_rule.return_value = rule
        mock_relational_store.update_rule.side_effect = lambda _id, updated: updated

        mgr = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            relational=mock_relational_store,
            auto_warmup=False,
        )
        updated = await mgr.update_memory("r1", content="When: X → Do: Z", is_user_locked=False)
        assert updated.content == "When: X → Do: Z"
        assert updated.is_user_locked is False

    @pytest.mark.asyncio
    async def test_omitted_lock_leaves_lock_untouched(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_relational_store: AsyncMock,
    ) -> None:
        """Editing without mentioning the lock must not silently release it."""
        rule = ProceduralMemory(content="When: X → Do: Y", trigger="X", action="Y", is_user_locked=True)
        mock_relational_store.get_rule.return_value = rule
        mock_relational_store.update_rule.side_effect = lambda _id, updated: updated

        mgr = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            relational=mock_relational_store,
            auto_warmup=False,
        )
        updated = await mgr.update_memory("r1", content="When: X → Do: Z")
        assert updated.is_user_locked is True
