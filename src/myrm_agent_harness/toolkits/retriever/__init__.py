"""retrievalhandlestool

providesvectorembedding, storageandretrieval'srelatedfeature.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.retriever.bm25_retrieval import bm25_retrieval
    from myrm_agent_harness.toolkits.retriever.embedding import EmbeddingService, get_embedding_service
    from myrm_agent_harness.toolkits.retriever.engine import (
        BM25CacheStats,
        RetrieverConfig,
        RetrieverManager,
    )
    from myrm_agent_harness.toolkits.retriever.hybrid_retriever import hybrid_retriever
    from myrm_agent_harness.toolkits.retriever.hybrid_search import HybridSearchCoordinator
    from myrm_agent_harness.toolkits.retriever.qdrant_retrieval import QdrantRetriever
    from myrm_agent_harness.toolkits.retriever.reranker import RerankerConfig, RerankerService, get_reranker_service
    from myrm_agent_harness.toolkits.retriever.splitter import TextChunker
    from myrm_agent_harness.toolkits.retriever.vector_search import (
        NumpyVectorRetriever,
        RetrievalResult,
        search_with_numpy_retriever,
    )

__all__ = [
    "BM25CacheStats",
    # Embedding service
    "EmbeddingService",
    # hybrid retrieval(newarchitecture)
    "HybridSearchCoordinator",
    # purememoryvectorretrieval(recommended)
    "NumpyVectorRetriever",
    # persistentvectorretrieval
    "QdrantRetriever",
    # Reranker service
    "RerankerConfig",
    "RerankerService",
    "RetrievalResult",
    "RetrieverConfig",
    # retrievalmanagerandconfiguration
    "RetrieverManager",
    # chunk
    "TextChunker",
    # BM25
    "bm25_retrieval",
    "get_embedding_service",
    "get_reranker_service",
    "hybrid_retriever",
    # pre-load function
    "preload_retriever_models",
    "preload_tokenizer",
    "search_with_numpy_retriever",
    "start_background_preload",
]

_LAZY_IMPORTS = {
    "bm25_retrieval": ("myrm_agent_harness.toolkits.retriever.bm25_retrieval", "bm25_retrieval"),
    "preload_tokenizer": ("myrm_agent_harness.toolkits.retriever.bm25.tokenizer", "preload_tokenizer"),
    "EmbeddingService": ("myrm_agent_harness.toolkits.retriever.embedding", "EmbeddingService"),
    "get_embedding_service": ("myrm_agent_harness.toolkits.retriever.embedding", "get_embedding_service"),
    "hybrid_retriever": ("myrm_agent_harness.toolkits.retriever.hybrid_retriever", "hybrid_retriever"),
    "HybridSearchCoordinator": ("myrm_agent_harness.toolkits.retriever.hybrid_search", "HybridSearchCoordinator"),
    "QdrantRetriever": ("myrm_agent_harness.toolkits.retriever.qdrant_retrieval", "QdrantRetriever"),
    "RerankerConfig": ("myrm_agent_harness.toolkits.retriever.reranker", "RerankerConfig"),
    "RerankerService": ("myrm_agent_harness.toolkits.retriever.reranker", "RerankerService"),
    "get_reranker_service": ("myrm_agent_harness.toolkits.retriever.reranker", "get_reranker_service"),
    "BM25CacheStats": ("myrm_agent_harness.toolkits.retriever.engine", "BM25CacheStats"),
    "RetrieverConfig": ("myrm_agent_harness.toolkits.retriever.engine", "RetrieverConfig"),
    "RetrieverManager": ("myrm_agent_harness.toolkits.retriever.engine", "RetrieverManager"),
    "TextChunker": ("myrm_agent_harness.toolkits.retriever.splitter", "TextChunker"),
    "NumpyVectorRetriever": ("myrm_agent_harness.toolkits.retriever.vector_search", "NumpyVectorRetriever"),
    "RetrievalResult": ("myrm_agent_harness.toolkits.retriever.vector_search", "RetrievalResult"),
    "search_with_numpy_retriever": (
        "myrm_agent_harness.toolkits.retriever.vector_search",
        "search_with_numpy_retriever",
    ),
}

if __debug__:
    _lazy_set = set(_LAZY_IMPORTS.keys())
    _all_set = set(__all__)
    _extra = _lazy_set - _all_set
    if _extra:
        raise RuntimeError(f"retriever: _LAZY_IMPORTS has symbols not in __all__: {_extra}")


def __getattr__(name: str):
    """Lazy load retriever components on first access."""
    if name in _LAZY_IMPORTS:
        from importlib import import_module

        module_path, attr_name = _LAZY_IMPORTS[name]
        module = import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value

    if name == "preload_retriever_models":
        import asyncio
        import logging

        from myrm_agent_harness.toolkits.retriever.bm25.tokenizer import preload_tokenizer

        logger = logging.getLogger(__name__)

        async def preload_retriever_models() -> list[BaseException | None]:
            """Preload retrieval models (tokenizer for BM25).

            Returns:
                Results for each preload task; None on success, exception on failure.
            """
            logger.warning("Preloading retrieval models...")

            results = await asyncio.gather(
                preload_tokenizer(),
                return_exceptions=True,
            )

            if isinstance(results[0], Exception):
                logger.error(f"Failed to preload tokenizer: {results[0]}")
            else:
                logger.warning("Tokenizer preloaded successfully")

            logger.warning("Retrieval models preloaded")
            return list(results)

        globals()[name] = preload_retriever_models
        return preload_retriever_models

    if name == "start_background_preload":
        import asyncio
        import logging
        import threading

        logger = logging.getLogger(__name__)

        def start_background_preload() -> threading.Thread:
            """inbackgroundthreadinstartmodelpre-load

            Returns:
                backgroundpre-loadthread
            """
            from myrm_agent_harness.toolkits.retriever import preload_retriever_models

            def _background_preload():
                loop = None
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    logger.warning("Starting background model loading...")
                    loop.run_until_complete(preload_retriever_models())
                    logger.warning("Background model loading completed")
                except Exception as e:
                    logger.error(f"Background model loading failed: {e}")
                finally:
                    if loop:
                        loop.close()

            thread = threading.Thread(target=_background_preload, daemon=True)
            thread.start()
            logger.warning("Background loading thread started")
            return thread

        globals()[name] = start_background_preload
        return start_background_preload

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
