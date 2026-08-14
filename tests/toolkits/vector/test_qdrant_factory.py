from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.vector.config import DeploymentMode
from myrm_agent_harness.toolkits.vector.qdrant import factory as qdrant_factory
from myrm_agent_harness.toolkits.vector.qdrant.factory import create_embedded_store


@pytest.fixture(autouse=True)
def _clear_embedded_cache():
    """Clear singleton cache between tests so stores never leak across cases."""
    qdrant_factory._embedded_clients.clear()
    yield
    qdrant_factory._embedded_clients.clear()


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
async def test_memory_fallback_isolated_per_path(tmp_path):
    """不同 base_path 的 fallback 必须隔离，不能共享同一内存 store。

    回归：fallback 统一 cache_key 为 "memory_fallback" 导致多个不可写路径
    共享同一个 in-memory Qdrant 实例（数据串写），且 evict 无法按原路径清理。
    """
    from unittest.mock import MagicMock, patch

    from myrm_agent_harness.toolkits.vector.qdrant.factory import (
        _embedded_clients,
        evict_embedded_store,
    )

    def fake_client(path: str, **kwargs: object) -> object:
        if path == ":memory:":
            return MagicMock()
        raise OSError("unwritable")

    path_a = tmp_path / "a" / "vector_store"
    path_b = tmp_path / "b" / "vector_store"

    with patch("qdrant_client.QdrantClient", side_effect=fake_client):
        store_a = await create_embedded_store(path=str(path_a))
        store_b = await create_embedded_store(path=str(path_b))

    # 两个不可写路径 fallback 后必须是相互独立的实例，绝不共享同一内存 store。
    assert store_a is not store_b

    key_a = f"{path_a.resolve()!s}:memory_fallback"
    key_b = f"{path_b.resolve()!s}:memory_fallback"
    assert key_a in _embedded_clients
    assert key_b in _embedded_clients

    # 通过原始路径 evict 必须能命中各自的 fallback store。
    await evict_embedded_store(str(path_a))
    assert key_a not in _embedded_clients
    assert key_b in _embedded_clients

    await evict_embedded_store(str(path_b))
    assert key_b not in _embedded_clients
    await store_a.hard_close()
    await store_b.hard_close()


@pytest.mark.asyncio
async def test_explicit_memory_does_not_share_fallback_key(tmp_path):
    """显式 :memory: 与 fallback store 不得共用 cache_key。

    回归：显式 ":memory:" 与不可写路径 fallback 此前共用 "memory_fallback"，
    测试用的内存 store 会被 fallback 数据污染。
    """
    from unittest.mock import MagicMock, patch

    from myrm_agent_harness.toolkits.vector.qdrant.factory import (
        _embedded_clients,
        evict_embedded_store,
    )

    def fake_client(path: str, **kwargs: object) -> object:
        if path == ":memory:":
            return MagicMock()
        raise OSError("unwritable")

    bad_path = tmp_path / "bad" / "vector_store"

    with patch("qdrant_client.QdrantClient", side_effect=fake_client):
        store_mem = await create_embedded_store(path=":memory:")
        store_fb = await create_embedded_store(path=str(bad_path))

    assert store_mem is not store_fb
    assert ":memory:" in _embedded_clients
    assert f"{bad_path.resolve()!s}:memory_fallback" in _embedded_clients

    await evict_embedded_store(":memory:")
    assert ":memory:" not in _embedded_clients
    await store_mem.hard_close()
    await evict_embedded_store(str(bad_path))
    await store_fb.hard_close()


@pytest.mark.asyncio
async def test_memory_fallback_repeat_returns_same_instance(tmp_path):
    """同一不可写路径重复调用必须返回同一实例，不得覆盖泄漏。

    回归：fallback 改写 cache_key 后未复查缓存，重复调用同一不可写路径
    会新建 store 覆盖缓存，旧 QdrantClient 泄漏且单例语义破坏。
    """
    from unittest.mock import MagicMock, patch

    from myrm_agent_harness.toolkits.vector.qdrant.factory import (
        evict_embedded_store,
    )

    def fake_client(path: str, **kwargs: object) -> object:
        if path == ":memory:":
            return MagicMock()
        raise OSError("unwritable")

    bad_path = tmp_path / "bad" / "vector_store"

    with patch("qdrant_client.QdrantClient", side_effect=fake_client) as mock_client:
        store1 = await create_embedded_store(path=str(bad_path))
        store2 = await create_embedded_store(path=str(bad_path))

    # 重复调用同一不可写路径必须命中同一 fallback store（单例语义）。
    assert store1 is store2
    # 只创建了一个 in-memory client，无覆盖泄漏。
    memory_calls = [
        call
        for call in mock_client.call_args_list
        if call.kwargs.get("path") == ":memory:"
    ]
    assert len(memory_calls) == 1

    await evict_embedded_store(str(bad_path))
    await store1.hard_close()


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
