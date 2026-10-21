"""Tests for CloudEmbedding dimension matching logic.

Verifies that model_variants correctly resolves KNOWN_MODEL_DIMENSIONS
for various model name formats (e.g. "BAAI/bge-m3", "openai/BAAI/bge-m3").
"""

import pytest

from myrm_agent_harness.toolkits.retriever.embedding.cloud_embedding import (
    KNOWN_MODEL_DIMENSIONS,
    CloudEmbedding,
)


class TestDimensionMatching:
    """Ensure model_variants includes the original model name for lookup."""

    def test_known_model_with_slash(self):
        svc = CloudEmbedding(model="BAAI/bge-m3", api_key="fake")
        assert svc.dimension == 1024

    def test_known_model_with_double_slash(self):
        svc = CloudEmbedding(model="Pro/BAAI/bge-m3", api_key="fake")
        assert svc.dimension == 1024

    def test_known_model_without_slash(self):
        svc = CloudEmbedding(model="text-embedding-3-small", api_key="fake")
        assert svc.dimension == 1536

    def test_unknown_model_dimension_is_none(self):
        svc = CloudEmbedding(model="unknown-model-xyz", api_key="fake")
        with pytest.raises(RuntimeError, match="not yet determined"):
            _ = svc.dimension

    @pytest.mark.parametrize("model", list(KNOWN_MODEL_DIMENSIONS.keys())[:5])
    def test_all_known_models_resolve(self, model: str):
        svc = CloudEmbedding(model=model, api_key="fake")
        assert svc.dimension == KNOWN_MODEL_DIMENSIONS[model]

    def test_prefixed_known_model_resolves(self):
        svc = CloudEmbedding(model="openai/text-embedding-3-small", api_key="fake")
        assert svc.dimension == 1536

    def test_baai_bge_large_zh(self):
        svc = CloudEmbedding(model="BAAI/bge-large-zh-v1.5", api_key="fake")
        assert svc.dimension == 1024
