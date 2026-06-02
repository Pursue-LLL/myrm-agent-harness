"""Hybrid retrieval entry point: exports `HybridSearchCoordinator` and module-level instance `hybrid_retriever`.

Implementation lives in the `hybrid_search` package; this module provides a stable import path.

[INPUT]
hybrid_search::HybridSearchCoordinator (POS: Orchestrates vector + BM25 hybrid search)

[OUTPUT]
hybrid_retriever: Pre-built module-level HybridSearchCoordinator instance
HybridSearchCoordinator: Re-exported coordinator class

[POS]
Stable public facade for hybrid retrieval. Re-exports the coordinator so callers need not
know about the internal `hybrid_search` package.

"""

from myrm_agent_harness.toolkits.retriever.hybrid_search import HybridSearchCoordinator

hybrid_retriever = HybridSearchCoordinator()

__all__ = ["HybridSearchCoordinator", "hybrid_retriever"]
