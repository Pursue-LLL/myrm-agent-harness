"""Sparse-only (embeddings-less) memory path — wrapper lifecycle, manager flows, delete.

Covers the embeddings-less degradation end to end on embedded Qdrant:
- BM25SparseIndexStore.upsert_sparse_only / get_sparse_only / delete_sparse_only;
- the storage-mixin fallbacks routing semantic/episodic writes to the sparse
  mirror when no embedding backend is configured;
- the deletion mixin reading and removing through the sparse mirror;
- create_local_memory_manager(embedding_config=None) assembling a working
  manager whose store/search/delete flows all reach the sparse channel.
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
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory
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
