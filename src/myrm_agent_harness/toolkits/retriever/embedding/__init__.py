"""Embedding Service Toolkit.

[INPUT]
- .base::EmbeddingService (POS: abstract embedding contract)
- .factory::get_embedding_service, get_embedding_config (POS: embedding service factory)

[OUTPUT]
- EmbeddingService, get_embedding_service, get_embedding_config

[POS]
Embedding 模块门面入口。提供统一的嵌入服务抽象与单例获取工厂。
"""

from myrm_agent_harness.toolkits.retriever.embedding.base import EmbeddingService
from myrm_agent_harness.toolkits.retriever.embedding.factory import get_embedding_config, get_embedding_service

__all__ = [
    "EmbeddingService",
    "get_embedding_config",
    "get_embedding_service",
]
