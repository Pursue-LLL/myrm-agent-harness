"""Tests for LocalEmbedding and factory fallback logic.

Verifies:
1. LocalEmbedding implements EmbeddingService correctly (with fastembed mocked)
2. Factory fallback: api_key → Cloud, no key + fastembed → Local, no key + no fastembed → RuntimeError
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import patch

import numpy as np
import pytest

from myrm_agent_harness.toolkits.retriever.embedding.base import EmbeddingService
from myrm_agent_harness.toolkits.retriever.embedding.factory import (
    EmbeddingConfig,
    _cache,
    _create_local_embedding_fallback,
    get_embedding_service,
)


@pytest.fixture()
def mock_fastembed():
    """Provide a fake fastembed module with a mock TextEmbedding class."""
    fake_module = ModuleType("fastembed")

    class FakeTextEmbedding:
        def __init__(self, model_name: str = "fake-model"):
            self.model_name = model_name

        def embed(self, texts: list[str]):
            return iter([np.ones(512, dtype=np.float32) for _ in texts])

    fake_module.TextEmbedding = FakeTextEmbedding  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {"fastembed": fake_module}):
        import importlib

        import myrm_agent_harness.toolkits.retriever.embedding.local_embedding as mod

        importlib.reload(mod)
        yield mod
        importlib.reload(mod)


class TestLocalEmbedding:
    """Test LocalEmbedding service implementation."""

    @pytest.fixture(autouse=True)
    def clear_factory_cache(self):
        _cache.clear()
        yield
        _cache.clear()

    def test_implements_embedding_service(self, mock_fastembed):
        """LocalEmbedding must be a proper subclass of EmbeddingService."""
        svc = mock_fastembed.LocalEmbedding()
        assert isinstance(svc, EmbeddingService)
        assert svc.dimension == 512

    @pytest.mark.asyncio
    async def test_embed_returns_correct_dimension(self, mock_fastembed):
        """embed() should return a list of floats with correct dimension."""
        svc = mock_fastembed.LocalEmbedding()
        result = await svc.embed("hello world")
        assert len(result) == 512
        assert all(isinstance(x, float) for x in result)

    @pytest.mark.asyncio
    async def test_embed_batch_returns_multiple_vectors(self, mock_fastembed):
        """embed_batch() should return one vector per input text."""
        svc = mock_fastembed.LocalEmbedding()
        results = await svc.embed_batch(["hello", "world"])
        assert len(results) == 2
        assert all(len(v) == 512 for v in results)

    @pytest.mark.asyncio
    async def test_embed_batch_empty_input(self, mock_fastembed):
        """embed_batch() with empty list returns empty list."""
        svc = mock_fastembed.LocalEmbedding()
        results = await svc.embed_batch([])
        assert results == []

    def test_import_error_when_fastembed_missing(self):
        """LocalEmbedding __init__ should raise ImportError if fastembed not installed."""
        with patch.dict(sys.modules, {"fastembed": None}):
            import importlib

            import myrm_agent_harness.toolkits.retriever.embedding.local_embedding as mod

            importlib.reload(mod)
            with pytest.raises(ImportError, match="fastembed"):
                mod.LocalEmbedding()


class TestFactoryFallback:
    """Test factory intelligent fallback logic."""

    @pytest.fixture(autouse=True)
    def clear_factory_cache(self):
        _cache.clear()
        yield
        _cache.clear()

    def test_cloud_embedding_when_api_key_present(self):
        """With API key, factory should create CloudEmbedding."""
        config = EmbeddingConfig(
            model="text-embedding-3-small",
            api_key="sk-test-key",
        )
        service = get_embedding_service(config)
        from myrm_agent_harness.toolkits.retriever.embedding.cloud_embedding import (
            CloudEmbedding,
        )

        assert isinstance(service, CloudEmbedding)

    def test_local_embedding_when_no_api_key_and_fastembed_available(
        self, mock_fastembed
    ):
        """Without API key but with fastembed, factory should create LocalEmbedding."""
        import importlib

        import myrm_agent_harness.toolkits.retriever.embedding.factory as factory_mod

        importlib.reload(factory_mod)

        config = EmbeddingConfig(model="local-model", api_key=None)
        service = factory_mod.get_embedding_service(config)

        assert isinstance(service, mock_fastembed.LocalEmbedding)

    def test_runtime_error_when_no_api_key_and_no_fastembed(self):
        """Without API key and without fastembed, factory should raise RuntimeError."""
        with patch.dict(sys.modules, {"fastembed": None}):
            import importlib

            import myrm_agent_harness.toolkits.retriever.embedding.local_embedding as local_mod

            importlib.reload(local_mod)

            config = EmbeddingConfig(model="any-model", api_key=None)
            with pytest.raises(RuntimeError, match="No embedding backend available"):
                get_embedding_service(config)

    def test_factory_caches_service_instance(self):
        """Same config should return the same cached instance."""
        config = EmbeddingConfig(
            model="text-embedding-3-small",
            api_key="sk-test-key",
        )
        service1 = get_embedding_service(config)
        service2 = get_embedding_service(config)
        assert service1 is service2

    def test_create_local_embedding_fallback_import_error(self):
        """_create_local_embedding_fallback raises RuntimeError when fastembed missing."""
        with patch.dict(sys.modules, {"fastembed": None}):
            import importlib

            import myrm_agent_harness.toolkits.retriever.embedding.local_embedding as local_mod

            importlib.reload(local_mod)

            with pytest.raises(RuntimeError, match="No embedding backend available"):
                _create_local_embedding_fallback()


class TestGetEmbeddingConfig:
    """Test get_embedding_config environment variable resolution."""

    def test_defaults_when_no_env(self):
        """Returns defaults when no env vars are set."""
        from myrm_agent_harness.toolkits.retriever.embedding.factory import (
            get_embedding_config,
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ):
            config = get_embedding_config()
        assert config.model == "text-embedding-3-small"
        assert config.api_key is None
        assert config.api_base is None

    def test_reads_embedding_specific_vars(self):
        """Reads EMBEDDING_* vars only ([T] test layer)."""
        from myrm_agent_harness.toolkits.retriever.embedding.factory import (
            get_embedding_config,
        )

        env = {
            "EMBEDDING_MODEL": "custom-model",
            "EMBEDDING_API_KEY": "embed-key",
            "EMBEDDING_BASE_URL": "https://embed.example.com",
            "OPENAI_API_KEY": "ignored",
            "BASIC_API_KEY": "ignored",
        }
        with patch.dict("os.environ", env, clear=True):
            config = get_embedding_config()
        assert config.model == "custom-model"
        assert config.api_key == "embed-key"
        assert config.api_base == "https://embed.example.com"

    def test_does_not_fall_back_to_openai_or_basic_vars(self):
        """OPENAI_* / BASIC_* are not used when EMBEDDING_* is absent."""
        from myrm_agent_harness.toolkits.retriever.embedding.factory import (
            get_embedding_config,
        )

        env = {
            "OPENAI_API_KEY": "openai-key",
            "OPENAI_BASE_URL": "https://openai.example.com",
            "BASIC_API_KEY": "basic-key",
            "BASIC_BASE_URL": "https://basic.example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            config = get_embedding_config()
        assert config.api_key is None
        assert config.api_base is None

    def test_get_embedding_service_uses_env_config(self):
        """get_embedding_service with no args reads EMBEDDING_* config from env."""
        from myrm_agent_harness.toolkits.retriever.embedding.factory import (
            get_embedding_service,
        )

        _cache.clear()
        env = {"EMBEDDING_API_KEY": "test-key"}
        with patch.dict("os.environ", env, clear=True):
            service = get_embedding_service()
        from myrm_agent_harness.toolkits.retriever.embedding.cloud_embedding import (
            CloudEmbedding,
        )

        assert isinstance(service, CloudEmbedding)
        _cache.clear()
