from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.vector.config import DeploymentMode, VectorStoreConfig
from myrm_agent_harness.toolkits.vector.qdrant import factory as qdrant_factory
from myrm_agent_harness.toolkits.vector.qdrant.factory import create_vector_store


@pytest.fixture(autouse=True)
def _clear_embedded_cache():
    """Clear singleton cache between tests."""
    qdrant_factory._embedded_clients.clear()
    yield
    qdrant_factory._embedded_clients.clear()


@pytest.mark.asyncio
async def test_qdrant_factory_memory_fallback():
    """验证当磁盘路径不可写时，Qdrant 自动降级到 :memory:"""
    config = VectorStoreConfig(mode=DeploymentMode.EMBEDDED, local_path="/non_existent_and_protected_path/qdrant")

    # 我们 mock 掉厂里的 QdrantClient (因为工厂内部是 local import)
    with patch("qdrant_client.QdrantClient") as mock_client:
        mock_client.return_value = MagicMock()

        store = await create_vector_store(config)

        # 验证回退成功
        assert store.config.local_path == ":memory:"
        assert store.config.mode == DeploymentMode.EMBEDDED


@pytest.mark.asyncio
async def test_qdrant_factory_success_local(tmp_path):
    """验证正常情况下使用本地路径"""
    path = tmp_path / "qdrant_data"
    config = VectorStoreConfig(mode=DeploymentMode.EMBEDDED, local_path=str(path))

    with patch("qdrant_client.QdrantClient") as mock_client:
        await create_vector_store(config)
        assert mock_client.call_count == 1
        # 验证传入了正确的路径
        assert mock_client.call_args.kwargs["path"] == str(path.resolve())
