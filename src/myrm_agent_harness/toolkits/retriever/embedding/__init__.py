"""Embedding Service Toolkit.

vectorembeddingserviceabstractlayer, unifiedusingcustom API:
- supports OpenAI / Azure OpenAI
- supportslocal Ollama (http://localhost:11434/v1)
- supportsits OpenAI compatibleservice

Example:
    ```python
    from myrm_agent_harness.toolkits.retriever.embedding import (
        get_embedding_service,
        EmbeddingService,
    )

    # usingdefaultconfigurationcreateservice
    service = get_embedding_service()

    # embeddingdocument
    vectors = await service.embed_batch(["Hello world", "hello world"])

    # embeddingquery
    query_vector = await service.embed("What is AI?")
    ```
"""

from myrm_agent_harness.toolkits.retriever.embedding.base import EmbeddingService
from myrm_agent_harness.toolkits.retriever.embedding.factory import get_embedding_config, get_embedding_service

__all__ = [
    "EmbeddingService",
    "get_embedding_config",
    "get_embedding_service",
]
