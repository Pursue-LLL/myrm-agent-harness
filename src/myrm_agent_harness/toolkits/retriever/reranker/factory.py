"""Reranker Service Factory.

Creates reranker service instances from configuration with process-level caching
(identical configs share a single instance).

[INPUT]
retriever.reranker.base::RerankerService (POS: Reranker contract layer)

[OUTPUT]
RerankerConfig: Frozen dataclass describing a reranker service configuration
create_reranker_service: Factory function returning a (possibly cached) RerankerService

[POS]
Reranker factory. Centralises reranker-service instantiation and ensures process-wide
singleton semantics per configuration tuple.

"""

import logging
from dataclasses import dataclass

from myrm_agent_harness.toolkits.retriever.reranker.base import RerankerService

logger = logging.getLogger(__name__)

_cache: dict[tuple[str, str | None, str | None], RerankerService] = {}


@dataclass(frozen=True)
class RerankerConfig:
    """Reranking service configuration.

    Attributes:
        model: Model name in LiteLLM format (e.g. "cohere/rerank-v3.5")
        api_key: API key
        api_base: API base URL (optional)
    """

    model: str
    api_key: str
    api_base: str | None = None


def get_reranker_service(config: RerankerConfig) -> RerankerService:
    """Get a reranker service instance (process-level cache, same config shares instance).

    Args:
        config: Reranking configuration (required)

    Returns:
        RerankerService instance

    Example:
        ```python
        config = RerankerConfig(
            model="cohere/rerank-v3.5",
            api_key="your_api_key"
        )
        reranker = get_reranker_service(config)
        ```
    """
    cache_key = (config.model, config.api_key, config.api_base)
    if cache_key in _cache:
        return _cache[cache_key]

    from myrm_agent_harness.toolkits.retriever.reranker.cloud_reranker import CloudReranker

    service = CloudReranker(
        model=config.model,
        api_key=config.api_key,
        api_base=config.api_base,
    )
    _cache[cache_key] = service
    return service


__all__ = [
    "RerankerConfig",
    "get_reranker_service",
]
