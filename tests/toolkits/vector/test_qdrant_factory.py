from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.vector.config import DeploymentMode
from myrm_agent_harness.toolkits.vector.qdrant.factory import create_embedded_store


@pytest.mark.asyncio
async def test_qdrant_embedded_init(tmp_path):
    # Test normal embedded init
    path = tmp_path / "vec_store"
    store = await create_embedded_store(path=str(path))

    assert store is not None
    assert store.config.mode == DeploymentMode.EMBEDDED
    assert Path(store.config.local_path).exists()

    await store.close()


@pytest.mark.asyncio
async def test_qdrant_memory_fallback():
    # Test fallback by using an invalid path
    invalid_path = "/non_existent_root/myrm_test"

    store = await create_embedded_store(path=invalid_path)

    assert store is not None
    assert store.config.mode == DeploymentMode.EMBEDDED
    assert store.config.local_path == ":memory:"

    # Healthy and usable
    assert await store.health_check() is True
    await store.close()


@pytest.mark.asyncio
async def test_singleton_per_path(tmp_path):
    path = str(tmp_path / "singleton")
    store1 = await create_embedded_store(path=path)
    store2 = await create_embedded_store(path=path)

    assert store1 is store2
    await store1.close()


@pytest.mark.asyncio
async def test_evict_embedded_store_releases_singleton(tmp_path):
    path = str(tmp_path / "evict_me")
    store1 = await create_embedded_store(path=path)
    assert await store1.health_check() is True

    from myrm_agent_harness.toolkits.vector.qdrant.factory import (
        _embedded_clients,
        evict_embedded_store,
    )

    assert path in _embedded_clients
    await evict_embedded_store(path)
    assert path not in _embedded_clients

    # A subsequent call creates a fresh store instead of reusing the evicted one.
    store2 = await create_embedded_store(path=path)
    assert store2 is not store1
    assert await store2.health_check() is True
    await evict_embedded_store(path)


@pytest.mark.asyncio
async def test_evict_embedded_store_unknown_path_noop():
    from myrm_agent_harness.toolkits.vector.qdrant.factory import (
        evict_embedded_store,
    )

    # Evicting a path with no cached store is a quiet no-op.
    await evict_embedded_store("/no/such/vector/store")


@pytest.mark.asyncio
async def test_clear_embedded_stores_empties_cache(tmp_path):
    from myrm_agent_harness.toolkits.vector.qdrant.factory import (
        _embedded_clients,
        clear_embedded_stores,
    )

    await create_embedded_store(path=str(tmp_path / "a"))
    await create_embedded_store(path=str(tmp_path / "b"))
    assert len(_embedded_clients) >= 2

    await clear_embedded_stores()
    assert _embedded_clients == {}
