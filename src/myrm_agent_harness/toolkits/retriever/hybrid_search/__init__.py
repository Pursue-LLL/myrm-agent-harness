"""Hybrid retrieval module.

provides BM25 + Vector检索 混合检索能力，Support重Sort and 多Query融合。

coreComponent：
- HybridSearchCoordinator: 混合检索协调器（主入口）
- FusionPipeline: Result融合管道
- RerankingPipeline: 重Sort管道

Usage example：
    ```python
    from myrm_agent_harness.toolkits.retriever.hybrid_search import HybridSearchCoordinator

    coordinator = HybridSearchCoordinator()
    results = await coordinator.search(
        queries=["Python tutorial", "Machine learning"],
        documents=[doc1, doc2, doc3],
        final_top_k=10,
    )
    ```
"""

from myrm_agent_harness.toolkits.retriever.hybrid_search.coordinator import HybridSearchCoordinator
from myrm_agent_harness.toolkits.retriever.hybrid_search.fusion_pipeline import FusionPipeline
from myrm_agent_harness.toolkits.retriever.hybrid_search.reranking_pipeline import RerankingPipeline

__all__ = [
    "FusionPipeline",
    "HybridSearchCoordinator",
    "RerankingPipeline",
]
