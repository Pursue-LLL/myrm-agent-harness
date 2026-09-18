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
from pathlib import Path
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
    EpisodicMemory,
    MemoryScope,
    MemoryStatus,
    ProceduralMemory,
    SemanticMemory,
    archive_retention_stamps,
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

    def test_archive_retention_stamps_pair_is_consistent(self) -> None:
        """Both stamps derive from one instant and span the retention window."""
        now = datetime.now(UTC)
        stamps = archive_retention_stamps(now)

        assert stamps["archived_at"] == now.isoformat()
        delta = datetime.fromisoformat(stamps["archive_expires_at"]) - datetime.fromisoformat(stamps["archived_at"])
        assert delta == timedelta(days=ARCHIVE_RETENTION_DAYS)

    @pytest.mark.asyncio
    async def test_staleness_review_archival_stamps_expires_at(self) -> None:
        """LLM-driven staleness removal must produce a reclaimable archive."""
        from myrm_agent_harness.toolkits.memory._internal.maintenance_service import (
            MaintenanceService,
        )

        now = datetime.now(UTC)
        config = MemoryConfig(embedding_model="test")
        docs: dict[str, VectorDocument] = {}
        memories = [
            EpisodicMemory(
                id=f"stale-{i}",
                content="stale event",
                event_type="observation",
                created_at=now - timedelta(days=120),
                expected_valid_days=1,
                metadata={},
            )
            for i in range(1, 4)  # StalenessReviewConfig.min_candidates defaults to 3
        ]
        for mem in memories:
            docs[mem.id] = VectorDocument(
                id=mem.id,
                content=mem.content,
                embedding=[0.1],
                metadata={
                    "memory_type": "episodic",
                    "status": "active",
                    "archived": False,
                    "expected_valid_days": 1,
                },
                created_at=mem.created_at,
                updated_at=now,
            )

        vector = AsyncMock()
        vector.get.side_effect = lambda _coll, ids, **_kw: [docs[i] for i in ids if i in docs]

        async def _upsert(_coll: str, batch: list[VectorDocument], **_kw: object) -> None:
            for doc in batch:
                docs[doc.id] = doc

        vector.upsert.side_effect = _upsert
        service = MaintenanceService(config=config, vector=vector, graph=None, relational=None)

        llm = AsyncMock(return_value='[{"id": "stale-1", "action": "remove", "reason": "outdated"}]')
        _reviewed, removed, _extended = await service._run_staleness_review(memories, llm)

        assert removed == 1
        archived = docs["stale-1"].metadata
        assert archived["status"] == "archived"
        assert isinstance(archived["archived_at"], str)
        expires_at = archived["archive_expires_at"]
        assert isinstance(expires_at, str)
        assert datetime.fromisoformat(expires_at) - datetime.fromisoformat(archived["archived_at"]) == timedelta(
            days=ARCHIVE_RETENTION_DAYS
        )

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

        # The same archived doc is returned for every scanned collection.
        assert purged == manager._vector.scroll.await_count  # type: ignore[attr-defined]
        assert purged == 3  # semantic + episodic + conversation
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

        assert purged == 3  # semantic + episodic + conversation
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


class TestPurgePagesThroughAllArchivedEntries:
    """Reclamation must not stop at the first page of archived entries."""

    def _manager(self, pages_by_collection: dict[str, list[tuple[list[VectorDocument], str | None]]]) -> object:
        from myrm_agent_harness.toolkits.memory.config import MemoryConfig as Cfg
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        vector = AsyncMock()
        seen: dict[str, int] = {}

        async def _scroll(collection: str, **kwargs: object) -> tuple[list[VectorDocument], str | None]:
            index = seen.get(collection, 0)
            seen[collection] = index + 1
            pages = pages_by_collection.get(collection, [])
            return pages[index] if index < len(pages) else ([], None)

        vector.scroll.side_effect = _scroll
        manager = MemoryManager(
            Cfg(embedding_model="test"),
            user_id="test_user",
            namespaces=["global"],
            vector=vector,
            auto_warmup=False,
        )
        manager.delete_memory = AsyncMock(side_effect=lambda _coll, ids: len(ids))  # type: ignore[method-assign]
        manager._scroll_seen = seen  # type: ignore[attr-defined]
        return manager

    @pytest.mark.asyncio
    async def test_entries_beyond_first_page_are_reclaimed(self) -> None:
        """A cursor continuation must be followed instead of discarded."""
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        first_page = [_archived_doc(f"p1-{i}", {"archive_expires_at": past}) for i in range(3)]
        second_page = [_archived_doc(f"p2-{i}", {"archive_expires_at": past}) for i in range(2)]
        config = MemoryConfig(embedding_model="test")
        # Semantic collection pages twice; episodic has a single page.
        manager = self._manager(
            {
                config.semantic_collection: [(first_page, "cursor-1"), (second_page, None)],                config.episodic_collection: [([_archived_doc("e1", {"archive_expires_at": past})], None)],
            }
        )

        purged = await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        assert purged == 6  # 3 + 2 semantic across pages, plus 1 episodic
        # One delete batch per collection, issued after the scan completes.
        assert manager.delete_memory.await_count == 2  # type: ignore[attr-defined]
        batches = [call.args[1] for call in manager.delete_memory.await_args_list]  # type: ignore[attr-defined]
        assert sorted(len(b) for b in batches) == [1, 5]

    @pytest.mark.asyncio
    async def test_scan_stops_when_cursor_is_exhausted(self) -> None:
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        config = MemoryConfig(embedding_model="test")
        doc = _archived_doc("only", {"archive_expires_at": past})
        manager = self._manager(
            {
                config.semantic_collection: [([doc], None)],
                config.episodic_collection: [([], None)],
            }
        )

        purged = await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        assert purged == 1
        # Exactly one scroll per collection: no cursor means no extra round trip.
        assert manager._scroll_seen == {  # type: ignore[attr-defined]
            config.semantic_collection: 1,
            config.episodic_collection: 1,
            config.conversation_collection: 1,
        }

    @pytest.mark.asyncio
    async def test_delete_batches_are_bounded(self) -> None:
        """One cycle must not cascade an unbounded number of graph deletions."""
        from myrm_agent_harness.toolkits.memory._manager.archival import _PURGE_DELETE_BATCH_SIZE

        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        total = _PURGE_DELETE_BATCH_SIZE * 2 + 7
        config = MemoryConfig(embedding_model="test")
        docs = [_archived_doc(f"m-{i}", {"archive_expires_at": past}) for i in range(total)]
        manager = self._manager(
            {
                config.semantic_collection: [(docs, None)],
                config.episodic_collection: [([], None)],
            }
        )

        purged = await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        assert purged == total
        batches = [len(call.args[1]) for call in manager.delete_memory.await_args_list]  # type: ignore[attr-defined]
        assert max(batches) <= _PURGE_DELETE_BATCH_SIZE
        assert sum(batches) == total

    @pytest.mark.asyncio
    async def test_cycle_deletion_budget_is_enforced(self) -> None:
        """One cycle stops at the deletion budget instead of running unbounded."""
        from myrm_agent_harness.toolkits.memory._manager.archival import (
            _MAX_PURGE_DELETIONS_PER_CYCLE,
        )

        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        total = _MAX_PURGE_DELETIONS_PER_CYCLE + 750
        config = MemoryConfig(embedding_model="test")
        docs = [_archived_doc(f"m-{i}", {"archive_expires_at": past}) for i in range(total)]
        manager = self._manager(
            {
                config.semantic_collection: [(docs, None)],
                config.episodic_collection: [([], None)],
            }
        )

        purged = await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        assert purged == _MAX_PURGE_DELETIONS_PER_CYCLE
        assert purged < total


class TestPurgeScansEveryArchivableCollection:
    """Reclamation must cover every collection that can hold an archived entry."""

    @pytest.mark.asyncio
    async def test_every_vector_collection_is_scanned(self) -> None:
        """A collection left out of the scan leaks entries forever."""
        from myrm_agent_harness.toolkits.memory.config import MemoryConfig as Cfg
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        config = Cfg(embedding_model="test")
        vector = AsyncMock()
        vector.scroll.return_value = ([], None)
        manager = MemoryManager(
            config, user_id="test_user", namespaces=["global"], vector=vector, auto_warmup=False
        )

        await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        scanned = {call.args[0] for call in vector.scroll.await_args_list}
        expected = {
            config.semantic_collection,
            config.episodic_collection,
            config.conversation_collection,
        }
        assert scanned == expected, f"collections not reclaimed: {sorted(expected - scanned)}"

    @pytest.mark.asyncio
    async def test_conversation_archive_is_reclaimed(self) -> None:
        """Conversation memories accept ARCHIVED status, so they are reachable."""
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        config = MemoryConfig(embedding_model="test")
        doc = _archived_doc("conv-1", {"archive_expires_at": past, "memory_type": "conversation"})

        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        vector = AsyncMock()
        vector.scroll.side_effect = lambda collection, **_kw: (
            ([doc], None) if collection == config.conversation_collection else ([], None)
        )
        manager = MemoryManager(
            config, user_id="test_user", namespaces=["global"], vector=vector, auto_warmup=False
        )
        manager.delete_memory = AsyncMock(side_effect=lambda _coll, ids: len(ids))  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        assert purged == 1
        assert manager.delete_memory.await_args.args[0] == config.conversation_collection  # type: ignore[attr-defined]


class TestPurgeFailureHandling:
    """Scan and list failures must degrade to a no-op instead of aborting the cycle."""

    @pytest.mark.asyncio
    async def test_scroll_failure_skips_collection(self) -> None:
        from myrm_agent_harness.toolkits.memory.config import MemoryConfig as Cfg
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        vector = AsyncMock()
        vector.scroll.side_effect = RuntimeError("qdrant unavailable")
        manager = MemoryManager(
            Cfg(embedding_model="test"), user_id="test_user", namespaces=["global"], vector=vector, auto_warmup=False
        )
        manager.delete_memory = AsyncMock(return_value=0)  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        assert purged == 0
        manager.delete_memory.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_missing_vector_backend_returns_zero(self) -> None:
        from myrm_agent_harness.toolkits.memory.config import MemoryConfig as Cfg
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        manager = MemoryManager(Cfg(embedding_model="test"), user_id="test_user", namespaces=["global"], auto_warmup=False)

        assert await manager.purge_expired_archived_memories() == 0  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_rule_listing_failure_returns_zero(self) -> None:
        from myrm_agent_harness.toolkits.memory.config import MemoryConfig as Cfg
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        relational = AsyncMock()
        relational.list_rules.side_effect = RuntimeError("sqlite unavailable")
        manager = MemoryManager(
            Cfg(embedding_model="test"),
            user_id="test_user",
            namespaces=["global"],
            relational=relational,
            auto_warmup=False,
        )

        assert await manager.purge_expired_archived_rules() == 0  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_rule_page_cap_stops_paging(self) -> None:
        """A full page over and over must stop at the cap, not loop forever."""
        from myrm_agent_harness.toolkits.memory._manager.archival import (
            _MAX_PURGE_RULE_PAGES,
            _PURGE_RULE_PAGE_SIZE,
        )
        from myrm_agent_harness.toolkits.memory.config import MemoryConfig as Cfg
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

        # Always return a full page so only the cap can end the loop.
        full_page = [
            ProceduralMemory(id=f"r-{i}", content="c", trigger="t", action="a", is_active=True)
            for i in range(_PURGE_RULE_PAGE_SIZE)
        ]
        relational = AsyncMock()
        relational.list_rules.return_value = full_page
        manager = MemoryManager(
            Cfg(embedding_model="test"),
            user_id="test_user",
            namespaces=["global"],
            relational=relational,
            auto_warmup=False,
        )
        manager.delete_rule = AsyncMock(return_value=True)  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_rules()  # type: ignore[attr-defined]

        assert purged == 0  # all rules are active, so none are reclaimed
        assert relational.list_rules.await_count == _MAX_PURGE_RULE_PAGES


    @pytest.mark.asyncio
    async def test_memory_page_cap_stops_scanning(self) -> None:
        """A cursor that never ends must stop at the cap and warn, not loop forever."""
        from myrm_agent_harness.toolkits.memory._manager.archival import (
            _MAX_PURGE_PAGES_PER_COLLECTION,
            _PURGE_PAGE_SIZE,
        )
        from myrm_agent_harness.toolkits.memory.config import MemoryConfig as Cfg
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager

        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        # Every page is full and always hands back another cursor.
        page = [_archived_doc(f"m-{i}", {"archive_expires_at": past}) for i in range(_PURGE_PAGE_SIZE)]
        vector = AsyncMock()
        vector.scroll.return_value = (page, "always-more")
        manager = MemoryManager(
            Cfg(embedding_model="test"), user_id="test_user", namespaces=["global"], vector=vector, auto_warmup=False
        )
        manager.delete_memory = AsyncMock(side_effect=lambda _coll, ids: len(ids))  # type: ignore[method-assign]

        purged = await manager.purge_expired_archived_memories()  # type: ignore[attr-defined]

        assert purged > 0
        # Three collections, each stopping exactly at the page cap.
        assert vector.scroll.await_count == _MAX_PURGE_PAGES_PER_COLLECTION * 3


class TestRetentionElapsedGuards:
    """``_retention_elapsed`` must stay safe on malformed or absent stamps."""

    def test_malformed_archived_at_is_not_treated_as_expired(self) -> None:
        from myrm_agent_harness.toolkits.memory._manager.archival import _retention_elapsed

        assert _retention_elapsed({"archived_at": "not-a-timestamp"}, datetime.now(UTC), 7) is False

    def test_non_string_stamps_are_not_treated_as_expired(self) -> None:
        from myrm_agent_harness.toolkits.memory._manager.archival import _retention_elapsed

        now = datetime.now(UTC)
        assert _retention_elapsed({"archive_expires_at": 12345}, now, 7) is False
        assert _retention_elapsed({"archived_at": None}, now, 7) is False
        assert _retention_elapsed({}, now, 7) is False

    def test_expires_at_takes_precedence_over_archived_at(self) -> None:
        from myrm_agent_harness.toolkits.memory._manager.archival import _retention_elapsed

        now = datetime.now(UTC)
        fresh_expiry = (now + timedelta(days=3)).isoformat()
        stale_archived = (now - timedelta(days=30)).isoformat()

        # An explicit future deadline wins over an old archived_at.
        assert _retention_elapsed({"archive_expires_at": fresh_expiry, "archived_at": stale_archived}, now, 7) is False


class TestArchiveFieldsSurviveRoundTrip:
    """Archive metadata must survive doc -> model -> doc unchanged.

    ``_COMMON_KNOWN_KEYS`` excludes keys from metadata passthrough, so any key
    listed there must be assigned onto the model by ``doc_to_*``. Listing one
    without that mapping silently destroys it on every read and write.
    """

    _ARCHIVE_KEYS = ("archived_at", "archive_expires_at", "archive_reason")

    @pytest.mark.parametrize(
        ("memory", "to_doc_name", "to_model_name"),
        [
            ("semantic", "semantic_to_doc", "doc_to_semantic"),
            ("episodic", "episodic_to_doc", "doc_to_episodic"),
        ],
    )
    def test_archive_metadata_survives_round_trip(
        self, memory: str, to_doc_name: str, to_model_name: str
    ) -> None:
        from myrm_agent_harness.toolkits.memory._internal import storage_converters

        to_doc = getattr(storage_converters, to_doc_name)
        to_model = getattr(storage_converters, to_model_name)
        now = datetime.now(UTC)
        scope = MemoryScope(primary_namespace="global", namespaces=["global"])

        instance: SemanticMemory | EpisodicMemory
        if memory == "semantic":
            instance = SemanticMemory(content="round-trip", scope=scope)
        else:
            instance = EpisodicMemory(content="round-trip", event_type="observation", scope=scope)
        instance.metadata = {
            **instance.metadata,
            **archive_retention_stamps(now),
            "archive_reason": "retention=0.100",
        }

        first_doc = to_doc(instance)
        restored = to_model(first_doc)
        second_doc = to_doc(restored)

        for key in self._ARCHIVE_KEYS:
            assert first_doc.metadata.get(key), f"{key} missing from initial payload"
            assert restored.metadata.get(key) is not None, f"{key} lost reading the payload back"
            assert second_doc.metadata.get(key) == first_doc.metadata.get(key), f"{key} mutated on rewrite"

    def test_conversation_archive_metadata_survives_round_trip(self) -> None:
        """Conversation memories accept ARCHIVED status, so their stamps must survive too."""
        from myrm_agent_harness.toolkits.memory._internal import storage_converters
        from myrm_agent_harness.toolkits.memory.types import ConversationMemory

        now = datetime.now(UTC)
        scope = MemoryScope(primary_namespace="global", namespaces=["global"])
        instance = ConversationMemory(content="summary", raw_exchange="Q/A", scope=scope)
        # The conversation payload injects these directly (no conversation_to_doc reverse path).
        doc = VectorDocument(
            id=instance.id,
            content=instance.content,
            embedding=[0.1],
            metadata={
                "memory_type": "conversation",
                "status": "archived",
                "archived": True,
                **archive_retention_stamps(now),
                "archive_reason": "user_deleted",
            },
            created_at=now,
            updated_at=now,
        )

        restored = storage_converters.doc_to_conversation(doc)

        for key in self._ARCHIVE_KEYS:
            assert restored.metadata.get(key), f"{key} lost reading an archived conversation"

    def test_conversation_converter_defaults_on_sparse_payload(self) -> None:
        """A minimal payload must still produce a usable conversation memory."""
        from myrm_agent_harness.toolkits.memory._internal import storage_converters

        doc = VectorDocument(id="conv-min", content="summary", embedding=[0.1], metadata={})

        restored = storage_converters.doc_to_conversation(doc)

        assert restored.id == "conv-min"
        assert restored.status == MemoryStatus.ACTIVE

    def test_conversation_converter_reads_raw_exchange(self) -> None:
        """The raw exchange decode path must return text, not raise."""
        from myrm_agent_harness.toolkits.memory._internal import storage_converters

        for payload in (
            {"raw_exchange": "plain Q/A"},
            {"raw_exchange": "plain", "raw_exchange_compressed": True},
            {"raw_exchange": ""},
        ):
            doc = VectorDocument(id="conv-raw", content="summary", embedding=[0.1], metadata=payload)

            restored = storage_converters.doc_to_conversation(doc, include_raw=True)

            assert isinstance(restored.raw_exchange, str)

    def test_conversation_converter_handles_timestamps(self) -> None:
        """A datetime, a valid string and a malformed string are all accepted."""
        from myrm_agent_harness.toolkits.memory._internal import storage_converters

        now = datetime.now(UTC)
        cases: list[tuple[dict[str, object], datetime]] = [
            ({"timestamp": now}, now),
            ({"timestamp": now.isoformat()}, now),
            ({"timestamp": "not-a-date"}, now),
            ({}, now),
        ]
        for payload, created in cases:
            doc = VectorDocument(
                id="conv-ts", content="s", embedding=[0.1], metadata=payload, created_at=created, updated_at=created
            )

            restored = storage_converters.doc_to_conversation(doc)

            assert restored.created_at == created


class TestArchiveWritePathsAreEnumerated:
    """Every archival write path must stamp the retention pair via one generator.

    A new archival path that hand-rolls the metadata keys can forget one of
    them, stranding the entry outside reclamation. This pins the current set.
    """

    _EXPECTED_WRITE_PATHS = 4

    def test_known_keys_exclude_archive_metadata(self) -> None:
        """Archive metadata persists through ``metadata``, not model attributes."""
        from myrm_agent_harness.toolkits.memory._internal.storage_converters import _COMMON_KNOWN_KEYS

        assert "archived_at" not in _COMMON_KNOWN_KEYS
        assert "archive_reason" not in _COMMON_KNOWN_KEYS
        assert "archive_expires_at" not in _COMMON_KNOWN_KEYS

    def test_every_archival_path_uses_the_shared_generator(self) -> None:
        """Archival metadata is never hand-assembled outside the generator."""
        memory_root = Path(__file__).resolve().parents[3] / "src" / "myrm_agent_harness" / "toolkits" / "memory"
        writers = [
            memory_root / "_internal" / "maintenance.py",
            memory_root / "_internal" / "maintenance_rule_forgetting.py",
            memory_root / "_internal" / "maintenance_service.py",
            memory_root / "_manager" / "mutations.py",
        ]
        assert len(writers) == self._EXPECTED_WRITE_PATHS

        for writer in writers:
            source = writer.read_text(encoding="utf-8")
            assert "archive_retention_stamps" in source, f"{writer.name} does not use the shared generator"
            assert 'metadata["archived_at"]' not in source, f"{writer.name} hand-writes archived_at"
            assert 'metadata["archive_expires_at"]' not in source, f"{writer.name} hand-writes archive_expires_at"
