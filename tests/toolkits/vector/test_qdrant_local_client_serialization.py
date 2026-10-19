"""The embedded Qdrant client must never be entered concurrently.

``asyncio.to_thread`` hands the synchronous embedded client to worker threads,
and a search fan-out issues several client calls at once. The client is not
thread-safe: interleaved calls used to lose writes (a delete could silently
keep its point, and later searches returned the deleted memory). One lock per
store serializes those calls — this test pins that invariant.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from uuid import uuid4

import pytest

from myrm_agent_harness.toolkits.vector.qdrant import create_embedded_store


@pytest.mark.asyncio
async def test_local_client_calls_are_serialized(tmp_path: Path) -> None:
    store = await create_embedded_store(path=str(tmp_path / "vector_store"))
    client = store._client  # type: ignore[attr-defined]
    original_retrieve = client.retrieve
    state = {"active": 0, "peak": 0}

    def tracking_retrieve(*args: object, **kwargs: object) -> object:
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        try:
            # A real blocking call: without the lock the worker threads overlap here.
            time.sleep(0.02)
            return original_retrieve(*args, **kwargs)
        finally:
            state["active"] -= 1

    client.retrieve = tracking_retrieve

    await asyncio.gather(*(store.get("missing-collection", [str(uuid4())]) for _ in range(6)))

    assert state["peak"] == 1


@pytest.mark.asyncio
async def test_concurrent_reads_and_delete_keep_the_delete(tmp_path: Path) -> None:
    """A delete racing a read fan-out still removes the point."""
    store = await create_embedded_store(path=str(tmp_path / "vector_store"))
    collection = "serialization-check"
    ids = [str(uuid4()) for _ in range(8)]
    await store.upsert(collection, [_document(one_id) for one_id in ids])

    await asyncio.gather(
        *(store.get(collection, [one_id]) for one_id in ids),
        store.delete(collection, ids[:4]),
    )

    docs, _ = await store.scroll(collection, limit=50)

    assert sorted(doc.id for doc in docs) == sorted(ids[4:])


def _document(collection_id: str):
    from datetime import UTC, datetime

    from myrm_agent_harness.toolkits.vector.base import VectorDocument

    now = datetime.now(UTC)
    return VectorDocument(
        id=collection_id,
        content=f"content {collection_id}",
        vector=[0.1, 0.2, 0.3, 0.4],
        metadata={},
        created_at=now,
        updated_at=now,
    )
