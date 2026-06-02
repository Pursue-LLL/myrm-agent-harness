"""Storage-agnostic protocols for the memory system."""

from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol
from myrm_agent_harness.toolkits.memory.protocols.conversation_search import ConversationSearchProtocol
from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphNode, GraphRelationship, GraphStoreProtocol
from myrm_agent_harness.toolkits.memory.protocols.hooks import (
    MemoryLifecycleHookProtocol,
    MemoryTurn,
    MemoryWriteAction,
)
from myrm_agent_harness.toolkits.memory.protocols.relational import RelationalStoreProtocol
from myrm_agent_harness.toolkits.memory.protocols.vector import (
    VectorDocument,
    VectorSearchResult,
    VectorStoreProtocol,
)

__all__ = [
    "ConversationSearchProtocol",
    "EmbeddingCacheProtocol",
    "EmbeddingProtocol",
    "GraphNode",
    "GraphRelationship",
    "GraphStoreProtocol",
    "MemoryLifecycleHookProtocol",
    "MemoryTurn",
    "MemoryWriteAction",
    "RelationalStoreProtocol",
    "VectorDocument",
    "VectorSearchResult",
    "VectorStoreProtocol",
]
