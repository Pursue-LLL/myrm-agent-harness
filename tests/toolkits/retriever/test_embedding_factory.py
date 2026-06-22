"""Tests for embedding factory."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.retriever.embedding.cloud_embedding import CloudEmbedding
from myrm_agent_harness.toolkits.retriever.embedding.factory import (
    EmbeddingConfig,
    _cache,
    get_embedding_service,
)


class TestEmbeddingFactory:
    """Test CloudEmbedding factory behavior."""

    @pytest.fixture(autouse=True)
    def clear_factory_cache(self):
        _cache.clear()
        yield
        _cache.clear()

    def test_cloud_embedding_when_api_key_present(self):
        config = EmbeddingConfig(
            model="text-embedding-3-small",
            api_key="sk-test-key",
        )
        service = get_embedding_service(config)
        assert isinstance(service, CloudEmbedding)

    def test_runtime_error_when_no_api_key(self):
        config = EmbeddingConfig(model="text-embedding-3-small", api_key=None)
        with pytest.raises(RuntimeError, match="No embedding backend available"):
            get_embedding_service(config)

    def test_factory_caches_by_config(self):
        config = EmbeddingConfig(model="text-embedding-3-small", api_key="sk-test-key")
        service1 = get_embedding_service(config)
        service2 = get_embedding_service(config)
        assert service1 is service2
