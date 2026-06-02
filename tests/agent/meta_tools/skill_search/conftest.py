"""Shared fixtures for skill_search tests.

Provides a deterministic mock EmbeddingService so tests don't depend on
real OpenAI API calls. Tests that need real embeddings should be marked
with @pytest.mark.integration.
"""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.retriever.embedding.base import EmbeddingService

_DIMENSION = 1536


class DeterministicEmbeddingService(EmbeddingService):
    """Deterministic embedding service for unit tests.

    Generates reproducible pseudo-embeddings from text content using
    a hash-based approach. Different texts produce different vectors,
    enabling meaningful similarity comparisons in tests.
    """

    @property
    def dimension(self) -> int:
        return _DIMENSION

    async def embed(self, text: str) -> list[float]:
        return self._hash_to_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_to_vector(t) for t in texts]

    @staticmethod
    def _hash_to_vector(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        values: list[float] = []
        for i in range(0, len(digest), 4):
            chunk = int.from_bytes(digest[i : i + 4], "big")
            values.append((chunk / 0xFFFFFFFF) * 2 - 1)
        while len(values) < _DIMENSION:
            extra_digest = hashlib.sha256(text.encode() + len(values).to_bytes(4, "big")).digest()
            for i in range(0, len(extra_digest), 4):
                chunk = int.from_bytes(extra_digest[i : i + 4], "big")
                values.append((chunk / 0xFFFFFFFF) * 2 - 1)
        return values[:_DIMENSION]


@pytest.fixture(autouse=True)
def _mock_embedding_service():
    """Auto-mock get_embedding_service to use deterministic embeddings.

    This prevents all skill_search tests from hitting real OpenAI API.
    Tests requiring real embeddings should use @pytest.mark.integration
    and override this fixture.
    """
    mock_service = DeterministicEmbeddingService()

    def fake_get_embedding_service(config, cache=None):
        return mock_service

    with patch(
        "myrm_agent_harness.toolkits.retriever.embedding.factory.get_embedding_service",
        side_effect=fake_get_embedding_service,
    ):
        yield mock_service
