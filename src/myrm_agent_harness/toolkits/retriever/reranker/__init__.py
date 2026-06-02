"""Reranker Service Toolkit.

Unified cloud reranking API abstraction layer:
- Cohere Rerank API (via LiteLLM)
- Jina AI Reranker API (via LiteLLM)
- Voyage AI Reranker API (via LiteLLM)
- OpenAI-compatible endpoints (SiliconFlow, etc.)

Example:
    ```python
    from myrm_agent_harness.toolkits.retriever.reranker import (
        RerankerConfig,
        RerankerService,
        get_reranker_service,
    )

    # Create config and get service instance
    config = RerankerConfig(
        model="cohere/rerank-v3.5",
        api_key="your_api_key"
    )
    service = get_reranker_service(config)

    # Rerank documents
    results = await service.rerank(
        query="What is AI?",
        documents=["AI is...", "Machine learning..."],
        top_k=5
    )
    ```
"""

from myrm_agent_harness.toolkits.retriever.reranker.base import RerankerService
from myrm_agent_harness.toolkits.retriever.reranker.factory import RerankerConfig, get_reranker_service

__all__ = [
    "RerankerConfig",
    "RerankerService",
    "get_reranker_service",
]
