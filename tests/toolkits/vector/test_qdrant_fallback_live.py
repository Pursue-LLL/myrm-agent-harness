"""Live verification: unwritable path falls back to a fully usable in-memory store.

Unit tests mock ``QdrantClient`` and only assert cache-key/eviction structure.
This module drives a *real* Qdrant instance to prove the fallback the production
``create_embedded_store`` relies on keeps the memory system fully usable:

- A truly unwritable path (blocker file / read-only dir) falls back to ``:memory:``.
- The fallback store accepts real collection creation, upserts and searches.
- Repeating the same unwritable path returns the same singleton (no overwrite leak).
- Two distinct unwritable paths stay isolated (no cross-path data bleed).
- ``evict_embedded_store`` releases the fallback key, and re-creation then
  provisions a fresh store.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.vector.base import VectorDocument
from myrm_agent_harness.toolkits.vector.qdrant.factory import (
    _embedded_clients,
    create_embedded_store,
    evict_embedded_store,
)

DIM = 8
_VECTOR = [0.1] * DIM


@pytest.fixture(autouse=True)
async def _clean_embedded_cache():
    """Clear singleton cache between cases so stores never leak across tests."""
    from myrm_agent_harness.toolkits.vector.qdrant.factory import clear_embedded_stores

    await clear_embedded_stores()
    assert _embedded_clients == {}
    yield
    await clear_embedded_stores()


def _blocker_path(tmp_path: Path) -> Path:
    """A path whose parent is a regular file, so Qdrant init must fail."""
    blocker = tmp_path / "blocker"
    blocker.write_text("occupied")
    return blocker / "vector_store"


def _readonly_path(tmp_path: Path) -> Path:
    """A path under a read-only directory, so Qdrant init must fail."""
    ro_dir = tmp_path / "ro"
    ro_dir.mkdir()
    os.chmod(ro_dir, 0o500)
    return ro_dir / "vector_store"


@pytest.mark.asyncio
async def test_fallback_store_is_fully_usable(tmp_path: Path) -> None:
    """Unwritable path falls back to a real in-memory store that can hold data."""
    bad_path = _blocker_path(tmp_path)
    store = await create_embedded_store(path=str(bad_path))

    assert store.config.local_path == ":memory:"
    assert await store.health_check() is True

    await store.create_collection("mem_fb", dimension=DIM, distance="cosine")
    await store.upsert(
        "mem_fb",
        [
            VectorDocument(id="fb-1", content="fallback works", vector=_VECTOR),
            VectorDocument(id="fb-2", content="still searchable", vector=[0.2] * DIM),
        ],
    )
    results = await store.search("mem_fb", _VECTOR, limit=10)
    contents = {r.document.content for r in results}
    assert "fallback works" in contents
    assert "still searchable" in contents

    await evict_embedded_store(str(bad_path))
    assert f"{bad_path.resolve()!s}:memory_fallback" not in _embedded_clients
    await store.hard_close()


@pytest.mark.asyncio
async def test_fallback_singleton_survives_repeat(tmp_path: Path) -> None:
    """Repeated creation of the same unwritable path reuses one instance."""
    bad_path = _readonly_path(tmp_path)
    store1 = await create_embedded_store(path=str(bad_path))
    store2 = await create_embedded_store(path=str(bad_path))

    assert store1 is store2
    assert store1.config.local_path == ":memory:"

    await evict_embedded_store(str(bad_path))
    await store1.hard_close()


@pytest.mark.asyncio
async def test_fallback_paths_stay_isolated(tmp_path: Path) -> None:
    """Two unwritable paths never share one in-memory instance."""
    path_a = _blocker_path(tmp_path)
    path_b = tmp_path / "other" / "blocker" / "vector_store"
    path_b.parent.parent.mkdir(parents=True)
    (path_b.parent.parent / "blocker").write_text("occupied")

    store_a = await create_embedded_store(path=str(path_a))
    store_b = await create_embedded_store(path=str(path_b))

    assert store_a is not store_b
    assert f"{path_a.resolve()!s}:memory_fallback" in _embedded_clients
    assert f"{path_b.resolve()!s}:memory_fallback" in _embedded_clients

    await evict_embedded_store(str(path_a))
    assert f"{path_a.resolve()!s}:memory_fallback" not in _embedded_clients
    assert f"{path_b.resolve()!s}:memory_fallback" in _embedded_clients

    await store_a.hard_close()
    await store_b.hard_close()


@pytest.mark.asyncio
async def test_fallback_recreated_after_evict(tmp_path: Path) -> None:
    """After eviction, the same unwritable path provisions a fresh fallback store."""
    bad_path = _blocker_path(tmp_path)
    store1 = await create_embedded_store(path=str(bad_path))
    key = f"{bad_path.resolve()!s}:memory_fallback"

    await evict_embedded_store(str(bad_path))
    assert key not in _embedded_clients

    store2 = await create_embedded_store(path=str(bad_path))
    assert store2 is not store1
    assert key in _embedded_clients
    assert await store2.health_check() is True

    await store1.hard_close()
    await evict_embedded_store(str(bad_path))
    await store2.hard_close()
