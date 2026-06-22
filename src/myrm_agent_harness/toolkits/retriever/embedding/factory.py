"""Embedding Service Factory.

Creates embedding service instances from configuration with process-level caching
(identical configs share a single instance).

[INPUT]
retriever.embedding.base::EmbeddingService (POS: Embedding contract layer)
memory.protocols.cache::EmbeddingCacheProtocol (POS: Cache protocol for embeddings)

[OUTPUT]
EmbeddingConfig: Frozen dataclass describing an embedding service configuration
create_embedding_service: Factory function returning a (possibly cached) EmbeddingService

[POS]
Embedding factory. Centralises embedding-service instantiation and ensures process-wide
singleton semantics per configuration tuple.

"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.retriever.embedding.base import EmbeddingService

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol

logger = logging.getLogger(__name__)

_cache: dict[tuple[str, str | None, str | None], EmbeddingService] = {}


@dataclass(frozen=True)
class EmbeddingConfig:
    """Embedding service configuration.

    Attributes:
        model: Model name in LiteLLM format (e.g. "text-embedding-3-small")
        api_key: Provider API key (required). For Ollama, use any non-empty placeholder.
        api_base: API base URL for self-hosted endpoints (e.g. http://localhost:11434/v1).
        max_retries: Maximum retry count for transient errors.
        retry_wait_min: Minimum retry wait time in seconds.
        retry_wait_max: Maximum retry wait time in seconds.
    """

    model: str
    api_key: str | None = None
    api_base: str | None = None
    max_retries: int = 2
    retry_wait_min: float = 1.0
    retry_wait_max: float = 4.0


def get_embedding_config() -> EmbeddingConfig:
    """Get embedding config from explicit ``EMBEDDING_*`` env vars ([T] test layer only).

    Production callers must inject ``EmbeddingConfig`` from WebUI Settings — no env fallback
    to OPENAI_* / BASIC_* / provider credentials.
    """
    import os

    model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    api_key = os.getenv("EMBEDDING_API_KEY")
    api_base = os.getenv("EMBEDDING_BASE_URL")
    return EmbeddingConfig(model=model, api_key=api_key, api_base=api_base)


def get_embedding_service(
    config: EmbeddingConfig | None = None,
    cache: EmbeddingCacheProtocol | None = None,
) -> EmbeddingService:
    """Get embedding service instance (CloudEmbedding via LiteLLM).

    Requires ``api_key`` in config. Local embedding uses Ollama or another OpenAI-compatible
    endpoint via ``api_base`` (e.g. http://localhost:11434/v1).

    Args:
        config: Embedding configuration. Defaults to environment-based config.
        cache: Optional embedding cache instance.
    """
    if config is None:
        config = get_embedding_config()

    cache_key = (config.model, config.api_key, config.api_base)
    if cache_key in _cache:
        return _cache[cache_key]

    if not config.api_key:
        raise RuntimeError(
            "No embedding backend available. Configure embedding in WebUI Settings "
            "(cloud API or Ollama via api_base), or set EMBEDDING_API_KEY for tests."
        )

    from myrm_agent_harness.toolkits.retriever.embedding.cloud_embedding import CloudEmbedding

    service = CloudEmbedding(
        model=config.model,
        api_key=config.api_key,
        api_base=config.api_base,
        cache=cache,
        max_retries=config.max_retries,
        retry_wait_min=config.retry_wait_min,
        retry_wait_max=config.retry_wait_max,
    )
    _cache[cache_key] = service
    return service


__all__ = [
    "EmbeddingConfig",
    "get_embedding_config",
    "get_embedding_service",
]
