"""Tests for user-protected memory write protection.

Covers:
- ``MemoryManager.update_memory`` refuses protected memories when
  ``allow_protected=False`` and permits them on the user-facing default
- ``confidence`` updates reach ``SemanticMemory``
- ``update_memory`` applies an explicit ``is_user_locked`` so the WebUI toggle
  can both protect and release a rule
- ``update_memory`` leaves the lock untouched when the caller omits it
- The agent-facing rejection message names the memory and the way out
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import MemoryProtectedError
from myrm_agent_harness.toolkits.memory.agent_surface.rule_write_boundary import (
    rule_write_protection_message,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory, SemanticMemory


class TestProtectionMessage:
    def test_message_names_the_memory_and_the_way_out(self) -> None:
        message = rule_write_protection_message("rule-42")
        assert "rule-42" in message
        assert "protected" in message
        assert "user" in message


class TestUpdateMemoryProtectionGuard:
    @pytest.mark.asyncio
    async def test_locked_rule_refused_for_automated_write(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_relational_store: AsyncMock,
    ) -> None:
        """Automated paths must not rewrite a rule the user locked."""
        from myrm_agent_harness.toolkits.memory.types import MemoryStatus

        rule = ProceduralMemory(
            id="r1", content="When: X → Do: Y", trigger="X", action="Y", is_user_locked=True
        )
        mock_relational_store.get_rule.return_value = rule

        mgr = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            relational=mock_relational_store,
            auto_warmup=False,
        )
        with pytest.raises(MemoryProtectedError):
            await mgr.update_memory("r1", status=MemoryStatus.DISABLED, allow_protected=False)
        mock_relational_store.update_rule.assert_not_called()

    @pytest.mark.asyncio
    async def test_pinned_memory_refused_for_automated_write(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
    ) -> None:
        """The guard covers vector memories too, not only procedural rules."""
        pinned = SemanticMemory(id="m1", content="critical", pinned=True)
        mgr = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )
        mgr.get_memory = AsyncMock(return_value=pinned)

        with pytest.raises(MemoryProtectedError):
            await mgr.update_memory("m1", content="rewritten", allow_protected=False)

    @pytest.mark.asyncio
    async def test_unlocked_rule_still_writable(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_relational_store: AsyncMock,
    ) -> None:
        rule = ProceduralMemory(
            id="r2", content="When: A → Do: B", trigger="A", action="B", is_user_locked=False
        )
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
        updated = await mgr.update_memory("r2", content="When: A → Do: C", allow_protected=False)
        assert updated.content == "When: A → Do: C"

    @pytest.mark.asyncio
    async def test_user_facing_default_still_writes_protected_memory(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_relational_store: AsyncMock,
    ) -> None:
        """The WebUI keeps the default: the user owns their own protected rules."""
        from myrm_agent_harness.toolkits.memory.types import MemoryStatus

        rule = ProceduralMemory(
            id="r3", content="When: X → Do: Y", trigger="X", action="Y", is_user_locked=True
        )
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
        updated = await mgr.update_memory("r3", status=MemoryStatus.ACTIVE)
        assert updated.status == MemoryStatus.ACTIVE


class TestUpdateMemoryConfidence:
    @pytest.mark.asyncio
    async def test_confidence_reaches_semantic_memory(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
    ) -> None:
        """Consolidation decay relies on ``confidence`` being writable."""
        memory = SemanticMemory(id="m1", content="fact", confidence=1.0)
        mock_vector_store.get.return_value = []
        mgr = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )
        mgr.get_memory = AsyncMock(return_value=memory)

        updated = await mgr.update_memory("m1", confidence=0.35, allow_protected=False)
        assert updated.confidence == 0.35


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


class TestCorrectMemoryProtectionGuard:
    @pytest.mark.asyncio
    async def test_pinned_memory_refused_for_agent_correction(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
    ) -> None:
        """``memory_manage(action=correct)`` must not demote a memory the user pinned."""
        pinned = SemanticMemory(id="m1", content="critical", pinned=True)
        mgr = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )
        mgr.get_memory = AsyncMock(return_value=pinned)

        with pytest.raises(MemoryProtectedError):
            await mgr.correct_memory("m1", "rewritten", allow_protected=False)
        mock_vector_store.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_facing_default_still_corrects_protected_memory(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
    ) -> None:
        """The WebUI keeps the default: the user owns their own protected data."""
        pinned = SemanticMemory(id="m1", content="critical", pinned=True)
        mgr = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )
        mgr.get_memory = AsyncMock(return_value=pinned)
        correction = SemanticMemory(id="m2", content="rewritten", correction_of="m1")
        mgr._store_semantic = AsyncMock(return_value=correction)

        result = await mgr.correct_memory("m1", "rewritten")

        assert result.correction_of == "m1"
        mock_vector_store.upsert.assert_called_once()
