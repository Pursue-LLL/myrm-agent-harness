"""Reads of a collection that does not exist answer empty, never raise.

Collections are created lazily on their first write, so a fresh install — and every
embeddings-less deployment, whose memories live in ``{collection}_bm25`` mirrors —
reads them before they exist. Qdrant answers such a read with
``ValueError("Collection X not found")``, which is an empty result rather than a
failure; a genuine backend error still propagates.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.vector.config import DeploymentMode, VectorStoreConfig
from myrm_agent_harness.toolkits.vector.qdrant.store import QdrantVectorStore

_READ_METHODS = ("query_points", "retrieve", "count", "scroll")


def _store_whose_reads_fail(exc: Exception) -> QdrantVectorStore:
    client = AsyncMock()
    for method in _READ_METHODS:
        getattr(client, method).side_effect = exc
    config = VectorStoreConfig(mode=DeploymentMode.REMOTE, url="http://localhost:6333", api_key="test")
    return QdrantVectorStore(client=client, config=config, is_async=True)


@pytest.mark.asyncio
async def test_reads_of_a_missing_collection_answer_empty() -> None:
    store = _store_whose_reads_fail(ValueError("Collection memory_semantic_missing not found"))

    assert await store.search("memory_semantic_missing", [0.1]) == []
    assert await store.search_multi_vector("memory_semantic_missing", {"summary": [0.1]}) == []
    assert await store.get("memory_semantic_missing", ["id"]) == []
    assert await store.count("memory_semantic_missing") == 0
    assert await store.scroll("memory_semantic_missing") == ([], None)


@pytest.mark.asyncio
async def test_a_backend_failure_still_raises() -> None:
    store = _store_whose_reads_fail(RuntimeError("backend down"))

    with pytest.raises(RuntimeError, match="backend down"):
        await store.count("memory_semantic_missing")
