"""Sparse-only (embeddings-less) memory path — wrapper lifecycle, manager flows, delete.

Covers the embeddings-less degradation end to end on embedded Qdrant:
- BM25SparseIndexStore.upsert_sparse_only / get_sparse_only / delete_sparse_only;
- the storage-mixin fallbacks routing semantic/episodic writes to the sparse
  mirror when no embedding backend is configured;
- the deletion mixin reading and removing through the sparse mirror;
- create_local_memory_manager(embedding_config=None) assembling a working
  manager whose store/search/delete flows all reach the sparse channel;
- the agent tool surface (save / search / rate / correct / delete);
- count / list / search agreement, delete_all, delete_by_type and the chat
  purge reaching the mirror;
- exact-duplicate suppression on the batch write path;
- the upgrade migration carrying keyword-mode memories into a configured
  embedding model (mirror-only orphan detection + reindex).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_index import (
    BM25SparseIndexStore,
    wrap_with_bm25_sparse_index,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemoryType, SemanticMemory
from myrm_agent_harness.toolkits.vector.base import VectorDocument

CONFIG = MemoryConfig(embedding_model="sparse-only", collection_prefix="spo")


def make_doc(content: str) -> VectorDocument:
    """Build an embeddings-less document with the payload keys the converters need."""
    now = datetime.now(UTC)
    return VectorDocument(
        id=str(uuid4()),
        content=content,
        vector=None,
        metadata={"user_id": "u1", "memory_type": "semantic", "archived": False},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.slow
class TestSparseOnlyWrapperLifecycle:
    @pytest.mark.asyncio
    async def test_upsert_get_delete_and_search_without_backfill(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.vector.qdrant import create_embedded_store

        store = await create_embedded_store(path=str(tmp_path / "qdrant"))
        wrapped = wrap_with_bm25_sparse_index(store)
        assert isinstance(wrapped, BM25SparseIndexStore)

        try:
            doc = make_doc("User prefers TypeScript strict mode with Vitest")
            ids = await wrapped.upsert_sparse_only(CONFIG.semantic_collection, [doc])
            assert ids == [doc.id]

            # The sparse channel serves immediately: no dense backfill ran.
            hits = await wrapped.bm25_search("vitest", CONFIG)
            assert hits is not None
            assert [h.memory.id for h in hits] == [doc.id]
            assert hits[0].memory.content == doc.content

            got = await wrapped.get_sparse_only(CONFIG.semantic_collection, [doc.id])
            assert [d.id for d in got] == [doc.id]

            deleted = await wrapped.delete_sparse_only(CONFIG.semantic_collection, [doc.id])
            assert deleted == 1
            gone = await wrapped.bm25_search("vitest", CONFIG)
            assert gone == []
            assert await wrapped.get_sparse_only(CONFIG.semantic_collection, [doc.id]) == []
        finally:
            await wrapped.close()


@pytest.mark.slow
class TestSparseOnlyManager:
    @pytest.mark.asyncio
    async def test_manager_write_search_delete_without_embedding(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager

        manager = await create_local_memory_manager(tmp_path / "mem", None)
        try:
            mem = SemanticMemory(
                id=str(uuid4()),
                user_id="sandbox_user",
                content="用户偏好用中文回复，代码风格喜欢详尽类型注解",
            )
            stored = await manager.store(mem)
            assert stored.id == mem.id

            hits = await manager.search("类型注解", limit=5)
            assert [h.memory.id for h in hits] == [mem.id]

            deleted = await manager.delete_memory_by_id(mem.id)
            assert deleted == 1
            assert await manager.search("类型注解", limit=5) == []
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_manager_episodic_write_and_search_without_embedding(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager

        manager = await create_local_memory_manager(tmp_path / "mem", None)
        try:
            episode = EpisodicMemory(
                id=str(uuid4()),
                user_id="sandbox_user",
                content="线上事故复盘：LiteLLM 网关重试风暴导致超时",
            )
            stored = await manager.store(episode)
            assert stored.id == episode.id

            hits = await manager.search("重试风暴", limit=5)
            assert [h.memory.id for h in hits] == [episode.id]
            assert hits[0].memory_type.value == "episodic"
        finally:
            await manager.close()


@pytest.mark.slow
class TestSparseOnlyAgentTools:
    """The agent tools stay usable when the deployment runs without embeddings.

    The write plane must not gate on dense capability: semantic/episodic
    memories live in the sparse mirror, so save / search / rate / correct /
    delete all stay reachable through the tool surface.
    """

    @pytest.mark.asyncio
    async def test_agent_tools_write_read_manage_without_embedding(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools import create_memory_tools
        from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager

        manager = await create_local_memory_manager(tmp_path / "mem", None)
        try:
            tools = {tool.name: tool for tool in create_memory_tools(manager)}

            saved = await tools["memory_save_tool"].coroutine(
                content="用户偏好 TypeScript strict 模式", category="knowledge"
            )
            assert saved.startswith("Knowledge stored (ID:")
            memory_id = saved.split("ID: ")[1].rstrip(")")

            hits = await manager.search("strict", limit=5)
            assert [h.memory.id for h in hits] == [memory_id]

            rated = await tools["memory_manage_tool"].coroutine(
                action="rate", memory_id=memory_id, category="knowledge", rating_score=5
            )
            assert rated.startswith("Memory rated")

            corrected = await tools["memory_manage_tool"].coroutine(
                action="correct",
                memory_id=memory_id,
                category="knowledge",
                new_content="用户偏好 TypeScript strict 模式与 Vitest",
            )
            assert corrected.startswith("Memory corrected")
            correction_id = corrected.split("new ID: ")[1].split(")")[0]

            deleted = await tools["memory_manage_tool"].coroutine(
                action="delete", memory_id=memory_id, category="knowledge"
            )
            assert deleted.startswith("Memory deleted")
            # The correction is a distinct memory and survives the original's deletion.
            assert [h.memory.id for h in await manager.search("strict", limit=5)] == [correction_id]

            event = await tools["memory_save_tool"].coroutine(content="线上事故复盘：重试风暴", category="event")
            assert event.startswith("Event stored (ID:")
        finally:
            await manager.close()


@pytest.mark.slow
class TestSparseOnlyLifecycle:
    """Counts and deletions must agree with what the mirror actually holds.

    The dense path derives both from the collection listing; without an embedding backend
    the memories live in the mirror alone, so a listing that only knows dense collections
    made ``delete_all`` report success while nothing was deleted.
    """

    @pytest.mark.asyncio
    async def test_count_list_and_search_agree_without_embedding(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager

        manager = await create_local_memory_manager(tmp_path / "mem", None)
        try:
            await manager.store_batch(
                [
                    SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content="用户偏好 TypeScript strict 模式"),
                    SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content="用户偏好 Vitest 优先"),
                ]
            )

            assert await manager.count_memories(MemoryType.SEMANTIC) == 2
            assert len(await manager.list_memories(MemoryType.SEMANTIC, limit=10)) == 2
            assert len(await manager.search("TypeScript", limit=5)) == 1
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_delete_all_empties_the_mirror(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager

        manager = await create_local_memory_manager(tmp_path / "mem", None)
        try:
            await manager.store_batch(
                [
                    SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content="清空校验：TypeScript strict"),
                    SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content="清空校验：Vitest 优先"),
                ]
            )

            counts = await manager.delete_all()

            assert counts.get(manager.config.semantic_collection) == 2
            assert await manager.search("TypeScript", limit=5) == []
            assert await manager.count_memories(MemoryType.SEMANTIC) == 0
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_delete_by_type_and_chat_purge_reach_the_mirror(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager

        manager = await create_local_memory_manager(tmp_path / "mem", None)
        try:
            chat_id = f"chat-{uuid4().hex}"
            semantic = SemanticMemory(
                id=str(uuid4()), user_id="sandbox_user", content="级联校验：TypeScript strict", source_chat_id=chat_id
            )
            episode = EpisodicMemory(
                id=str(uuid4()), user_id="sandbox_user", content="级联校验：重试风暴复盘", source_chat_id=chat_id
            )
            await manager.store_batch([semantic, episode])

            ids = await manager.list_memory_ids_by_metadata("source_chat_id", chat_id)
            assert ids["semantic"] == [semantic.id]
            assert ids["episodic"] == [episode.id]

            assert await manager.delete_by_type(MemoryType.SEMANTIC) == 1
            assert await manager.count_memories(MemoryType.SEMANTIC) == 0
            assert await manager.count_memories(MemoryType.EPISODIC) == 1

            purged = await manager.purge_by_source_chat_id(chat_id)
            assert purged["episodic"] == 1
            assert await manager.search("重试风暴", limit=5) == []
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_conversation_reads_answer_empty_without_embedding(self, tmp_path: Path) -> None:
        """Conversations are never stored without embeddings: reading them answers empty, not an error."""
        from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager

        manager = await create_local_memory_manager(tmp_path / "mem", None)
        try:
            assert await manager.count_memories(MemoryType.CONVERSATION) == 0
            assert await manager.list_memories(MemoryType.CONVERSATION, limit=5) == []
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_exact_duplicate_content_is_dropped(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager

        manager = await create_local_memory_manager(tmp_path / "mem", None)
        try:
            content = "去重校验：用户偏好 TypeScript strict 模式"
            await manager.store_batch(
                [
                    SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content=content),
                    SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content=content),
                    SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content="去重校验：用户偏好 Vitest 优先"),
                ]
            )
            assert await manager.count_memories(MemoryType.SEMANTIC) == 2

            # A later batch re-extracting the same fact does not pile up another copy.
            await manager.store_batch([SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content=content)])
            assert await manager.count_memories(MemoryType.SEMANTIC) == 2
        finally:
            await manager.close()


class _KeywordUpgradeEmbedder:
    """Deterministic embedder for the upgrade-migration test (no model call)."""

    dimension = 8

    async def embed(self, text: str) -> list[float]:
        return [float(len(text) % 5 + 1)] + [0.5] * (self.dimension - 1)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


@pytest.mark.slow
class TestSparseOnlyUpgradeMigration:
    """Keyword-mode memories must survive the switch to an embedding model."""

    @pytest.mark.asyncio
    async def test_keyword_mode_mirror_is_not_an_orphan(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager

        manager = await create_local_memory_manager(tmp_path / "mem", None)
        try:
            await manager.store(SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content="孤儿校验：TypeScript"))
            assert await manager.detect_orphan_collections() == []
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_delete_all_reaches_an_unmigrated_keyword_mirror(self, tmp_path: Path) -> None:
        """Clearing memories in a dense deployment must also clear a mirror left by keyword mode.

        Otherwise the memories survive the clear and reappear on the next migration.
        """
        from myrm_agent_harness.toolkits.memory.config import MemoryConfig
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager
        from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager
        from myrm_agent_harness.toolkits.vector.qdrant import create_embedded_store

        base = tmp_path / "mem"
        keyword = await create_local_memory_manager(base, None)
        mirror = f"{keyword.config.semantic_collection}_bm25"
        memory = SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content="窗口期校验：TypeScript strict")
        try:
            await keyword.store(memory)
        finally:
            await keyword.close()

        store = await create_embedded_store(path=str(base / "vector_store"))
        manager = MemoryManager(
            MemoryConfig(embedding_model="upgrade-test-model"),
            user_id="sandbox_user",
            vector=store,
            embedding=_KeywordUpgradeEmbedder(),  # type: ignore[arg-type]
            auto_warmup=False,
        )
        try:
            assert await store.count(mirror) == 1

            counts = await manager.delete_all()

            assert counts.get(mirror) == 1
            assert await store.count(mirror) == 0
            assert await manager.detect_orphan_collections() == []
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_keyword_memories_migrate_into_the_configured_model(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.memory.config import MemoryConfig
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager
        from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager
        from myrm_agent_harness.toolkits.vector.qdrant import create_embedded_store

        base = tmp_path / "mem"
        keyword = await create_local_memory_manager(base, None)
        mirror = f"{keyword.config.semantic_collection}_bm25"
        memories = [
            SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content="迁移校验：TypeScript strict 模式"),
            SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content="迁移校验：Vitest 优先"),
        ]
        try:
            await keyword.store_batch(memories)
        finally:
            await keyword.close()

        store = await create_embedded_store(path=str(base / "vector_store"))
        config = MemoryConfig(embedding_model="upgrade-test-model")
        manager = MemoryManager(
            config,
            user_id="sandbox_user",
            vector=store,
            embedding=_KeywordUpgradeEmbedder(),  # type: ignore[arg-type]
            auto_warmup=False,
        )
        try:
            orphans = await manager.detect_orphan_collections()
            assert [(o.collection_name, o.document_count) for o in orphans] == [(mirror, 2)]

            result = await manager.reindex_from_orphans()

            assert result.migrated == 2
            assert result.failed == 0
            assert await manager.detect_orphan_collections() == []
            assert await store.collection_exists(mirror) is False
            moved = await store.get(config.semantic_collection, [m.id for m in memories])
            assert {d.id for d in moved} == {m.id for m in memories}
            assert {d.content for d in moved} == {m.content for m in memories}
        finally:
            await manager.close()
