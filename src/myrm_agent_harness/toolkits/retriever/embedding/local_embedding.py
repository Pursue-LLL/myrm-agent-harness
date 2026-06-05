"""Local Embedding Implementation.

Offline-capable embedding backend using fastembed (ONNX Runtime).
Enables full vector search for users without cloud embedding API keys.

[INPUT]
retriever.embedding.base::EmbeddingService (POS: Embedding contract layer)

[OUTPUT]
LocalEmbedding: Concrete EmbeddingService backed by local ONNX model via fastembed

[POS]
Local embedding backend. Provides zero-cost, offline-capable vector embeddings
using fastembed's ONNX runtime. Automatically activated when no cloud API key is available.

"""

from __future__ import annotations

import asyncio
import logging

from myrm_agent_harness.toolkits.retriever.embedding.base import EmbeddingService

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_DIMENSION = 512


class LocalEmbedding(EmbeddingService):
    """Local ONNX-based embedding using fastembed.

    Runs entirely on CPU without any network calls. Model is downloaded once
    (~25MB) on first use and cached permanently in the fastembed cache directory.

    Args:
        model_name: fastembed model identifier. If None, reads LOCAL_EMBEDDING_MODEL
                    env var, falling back to BAAI/bge-small-zh-v1.5 (CJK + English).
    """

    def __init__(self, model_name: str | None = None):
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise ImportError(
                "fastembed is required for local embeddings. Install with: uv add 'myrm-agent-harness[local-embedding]'"
            ) from e

        import os

        self._model_name = model_name or os.getenv("LOCAL_EMBEDDING_MODEL", DEFAULT_MODEL)
        self._text_embedding = TextEmbedding(model_name=self._model_name)
        self._dimension = self._detect_dimension()

        logger.info(
            "Local embedding initialized: %s | dim=%d",
            model_name,
            self._dimension,
        )

    def _detect_dimension(self) -> int:
        """Detect embedding dimension by running a probe."""
        probe_result = list(self._text_embedding.embed(["dimension probe"]))
        if probe_result:
            return len(probe_result[0])
        return DEFAULT_DIMENSION

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        results = await asyncio.to_thread(lambda: list(self._text_embedding.embed([text])))
        return results[0].tolist() if results else [0.0] * self._dimension

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results = await asyncio.to_thread(lambda: list(self._text_embedding.embed(texts)))
        return [vec.tolist() for vec in results]
