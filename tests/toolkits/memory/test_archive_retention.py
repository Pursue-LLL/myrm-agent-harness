"""Regression tests for the archive retention contract.

Covers:
- Every ARCHIVE write path stamps ``archive_expires_at`` so the purge scanner
  can reclaim the entry later.
- ``purge_expired_archived_memories`` reclaims entries by expiration stamp and
  falls back to ``archived_at`` + TTL for entries stamped before the contract.
- ``purge_expired_archived_rules`` reclaims archived rules while leaving
  user-protected rules recoverable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import run_forgetting
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
    ForgettingConfig,
    ForgettingMode,
)
from myrm_agent_harness.toolkits.memory.types import (
    ARCHIVE_RETENTION_DAYS,
    ProceduralMemory,
    SemanticMemory,
)


def _archived_doc(doc_id: str, metadata: dict[str, object]) -> VectorDocument:
    base: dict[str, object] = {
        "status": "archived",
        "archived": True,
        "memory_type": "semantic",
    }
    base.update(metadata)
    return VectorDocument(id=doc_id, content="archived", metadata=base, embedding=[0.1])


class TestArchiveWriteStampsExpiration:
    """The ARCHIVE forgetting path must stamp the purge contract field."""

    @pytest.mark.asyncio
    async def test_run_forgetting_archive_stamps_expires_at(self) -> None:
        config = MemoryConfig(
            embedding_model="test",
            forgetting=ForgettingConfig(mode=ForgettingMode.ARCHIVE, max_forget_per_run=10),
        )
        vector = AsyncMock()
        doc = VectorDocument(id="doc1", content="test", metadata={"importance": 0.1}, embedding=[0.1])
        vector.scroll.side_effect = [([doc], None), ([], None)]

        with patch(
            "myrm_agent_harness.toolkits.memory.strategies.forgetting.ForgettingStrategy.select_candidates"
        ) as mock_select:
            mock_select.return_value = [
                (SemanticMemory(id="doc1", content="test", metadata={}), AsyncMock(total_score=0.1))
            ]
            result = await run_forgetting(vector, config)

        assert result.archived_count == 1
        upserted = vector.upsert.await_args_list[0].args[1][0]
        expires_at = upserted.metadata["archive_expires_at"]
        assert isinstance(expires_at, str)
        archived_at = datetime.fromisoformat(upserted.metadata["archived_at"])
        assert datetime.fromisoformat(expires_at) - archived_at == timedelta(days=ARCHIVE_RETENTION_DAYS)


class TestPurgeExpiredArchivedMemories:
    """The purge scanner must honour the stamp and fall back to ``archived_at``."""

    def _manager(self, docs: list[VectorDocument]) -> object:
        from myrm_agent_harness.toolkits.memory.config import MemoryConfig as Cfg
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        vector = AsyncMock()
        vector.scroll.return_value = (docs, None)
        return MemoryManager(
            Cfg(embedding_model="test"),
            user_id="test_user",
            namespaces=["global"],
            vector=vector,
            auto_warmup=False,
        )

    @pytest.mark.asyncio
    async def test_expired_stamp_is_reclaimed(self) -> None:
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        docs = [_archived_doc("expired", {"archive_expires_at": past})]
        manager = self._manager(docs)
        manager.delete_memory = AsyncMock(return_value=1)  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        assert purged == 2  # one per collection scan
        manager.delete_memory.assert_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_future_stamp_is_retained(self) -> None:
        future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        docs = [_archived_doc("fresh", {"archive_expires_at": future})]
        manager = self._manager(docs)
        manager.delete_memory = AsyncMock(return_value=0)  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        assert purged == 0
        manager.delete_memory.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_missing_stamp_falls_back_to_archived_at(self) -> None:
        """Entries archived before the contract must still be reclaimed."""
        stale = (datetime.now(UTC) - timedelta(days=ARCHIVE_RETENTION_DAYS + 1)).isoformat()
        docs = [_archived_doc("legacy", {"archived_at": stale})]
        manager = self._manager(docs)
        manager.delete_memory = AsyncMock(return_value=1)  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        assert purged == 2
        manager.delete_memory.assert_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_recent_legacy_entry_is_retained(self) -> None:
        recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        docs = [_archived_doc("recent-legacy", {"archived_at": recent})]
        manager = self._manager(docs)
        manager.delete_memory = AsyncMock(return_value=0)  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        assert purged == 0


class TestPurgeExpiredArchivedRules:
    """Archived rules must be reclaimable, minus user-protected ones."""

    def _manager(self, rules: list[ProceduralMemory]) -> object:
        from myrm_agent_harness.toolkits.memory.config import MemoryConfig as Cfg
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        relational = AsyncMock()
        relational.list_rules.return_value = rules
        return MemoryManager(
            Cfg(embedding_model="test"),
            user_id="test_user",
            namespaces=["global"],
            relational=relational,
            auto_warmup=False,
        )

    def _archived_rule(self, rule_id: str, *, expires_at: str | None) -> ProceduralMemory:
        metadata: dict[str, object] = {"archived_at": (datetime.now(UTC) - timedelta(days=30)).isoformat()}
        if expires_at is not None:
            metadata["archive_expires_at"] = expires_at
        return ProceduralMemory(
            id=rule_id,
            content="archived rule",
            trigger="t",
            action="a",
            is_active=False,
            created_at=datetime.now(UTC) - timedelta(days=60),
            metadata=metadata,
        )

    @pytest.mark.asyncio
    async def test_expired_rule_is_deleted(self) -> None:
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        manager = self._manager([self._archived_rule("r1", expires_at=past)])
        manager.delete_rule = AsyncMock(return_value=True)  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_rules()  # type: ignore[attr-defined]

        assert purged == 1
        manager.delete_rule.assert_awaited_once_with("r1", allow_protected=False)  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_missing_stamp_falls_back_to_archived_at(self) -> None:
        manager = self._manager([self._archived_rule("r2", expires_at=None)])
        manager.delete_rule = AsyncMock(return_value=True)  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_rules()  # type: ignore[attr-defined]

        assert purged == 1

    @pytest.mark.asyncio
    async def test_future_stamp_rule_is_retained(self) -> None:
        future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        manager = self._manager([self._archived_rule("r3", expires_at=future)])
        manager.delete_rule = AsyncMock(return_value=True)  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_rules()  # type: ignore[attr-defined]

        assert purged == 0
        manager.delete_rule.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_active_rule_is_never_purged(self) -> None:
        rule = self._archived_rule("r4", expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat())
        rule.is_active = True
        manager = self._manager([rule])
        manager.delete_rule = AsyncMock(return_value=True)  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_rules()  # type: ignore[attr-defined]

        assert purged == 0

    @pytest.mark.asyncio
    async def test_user_protected_rule_is_skipped(self) -> None:
        """``allow_protected=False`` keeps user-endorsed rules recoverable."""
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        manager = self._manager([self._archived_rule("r5", expires_at=past)])
        manager.delete_rule = AsyncMock(return_value=False)  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_rules()  # type: ignore[attr-defined]

        assert purged == 0
