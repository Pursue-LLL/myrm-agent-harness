"""Pure in-memory vector retrieval module

Provides high-performance NumPy-based in-memory vector retrieval for temporary document sets (web search results, crawled content, etc.)。
"""

from myrm_agent_harness.toolkits.retriever.vector_search.numpy_retriever import (
    NumpyVectorRetriever,
    RetrievalResult,
    search_with_numpy_retriever,
)

__all__ = [
    "NumpyVectorRetriever",
    "RetrievalResult",
    "search_with_numpy_retriever",
]
