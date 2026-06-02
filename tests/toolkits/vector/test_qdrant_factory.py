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
