from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.vector.config import DeploymentMode, VectorStoreConfig
from myrm_agent_harness.toolkits.vector.qdrant.factory import (
    create_embedded_store,
    create_remote_store,
    create_vector_store,
)


@pytest.mark.asyncio
async def test_qdrant_factory_remote():
    """Test remote Qdrant store creation."""
    config = VectorStoreConfig(mode=DeploymentMode.REMOTE, url="http://localhost:6333", api_key="test_key")

    with patch("qdrant_client.AsyncQdrantClient") as mock_client:
        mock_client.return_value = MagicMock()
        store = await create_vector_store(config)

        assert store.config.mode == DeploymentMode.REMOTE
        assert store.config.url == "http://localhost:6333"
        assert store.config.api_key == "test_key"

@pytest.mark.asyncio
async def test_qdrant_factory_remote_direct():
    """Test remote Qdrant store creation directly."""
    with patch("qdrant_client.AsyncQdrantClient") as mock_client:
        mock_client.return_value = MagicMock()
        store = create_remote_store(url="http://localhost:6333", api_key="test_key")

        assert store.config.mode == DeploymentMode.REMOTE
        assert store.config.url == "http://localhost:6333"

@pytest.mark.asyncio
async def test_qdrant_factory_memory_direct():
    """Test embedded Qdrant store creation with :memory:."""
    with patch("qdrant_client.QdrantClient") as mock_client:
        mock_client.return_value = MagicMock()
        store = await create_embedded_store(path=":memory:")

        assert store.config.mode == DeploymentMode.EMBEDDED
        assert store.config.local_path == ":memory:"

@pytest.mark.asyncio
async def test_qdrant_factory_unknown_mode():
    """Test unknown mode."""
    config = VectorStoreConfig(mode=DeploymentMode.EMBEDDED)
    config.mode = "UNKNOWN"  # Bypass pydantic validation for testing
    with pytest.raises(ValueError):
        await create_vector_store(config)
