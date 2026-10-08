"""End-to-end orchestrator executing goal-driven quadruple retrieval pipeline.

[INPUT]
- toolkits.memory.quadruple_retrieval.goal_parser::TaskGoalParser (POS: Pre-retrieval task goal parser deconstructing complex user queries into explicit constraints.)
- toolkits.memory.quadruple_retrieval.models::QuadrupleRetrievalReport, RerankedMemoryHit (POS: Domain models and data structures for goal-driven quadruple retrieval and reasoner suite.)
- toolkits.memory.quadruple_retrieval.parallel_retriever::MemoryStoreItem, QuadrupleParallelRetriever (POS: Quadruple parallel recall executor with multi-channel fusion and deduplication.)
- toolkits.memory.quadruple_retrieval.reasoner::ReasonerReranker (POS: Reasoner module evaluating candidate relevance, staleness, and context harmonization.)

[OUTPUT]
- QuadrupleRetrievalOrchestrator: High-level orchestrator executing query deconstruction, parallel recall, fusion, and reasoner reranking.

[POS]
End-to-end orchestrator executing goal-driven quadruple retrieval pipeline.
"""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.memory.quadruple_retrieval.goal_parser import (
    TaskGoalParser,
)
from myrm_agent_harness.toolkits.memory.quadruple_retrieval.models import (
    QuadrupleRetrievalReport,
    RerankedMemoryHit,
)
from myrm_agent_harness.toolkits.memory.quadruple_retrieval.parallel_retriever import (
    MemoryStoreItem,
    QuadrupleParallelRetriever,
)
from myrm_agent_harness.toolkits.memory.quadruple_retrieval.reasoner import (
    ReasonerReranker,
)


class QuadrupleRetrievalOrchestrator:
    """High-level pipeline coordinator orchestrating goal parsing, 4-way parallel recall, and reasoner reranking."""

    def __init__(
        self,
        parser: TaskGoalParser | None = None,
        retriever: QuadrupleParallelRetriever | None = None,
        reasoner: ReasonerReranker | None = None,
    ) -> None:
        self._parser = parser or TaskGoalParser()
        self._retriever = retriever or QuadrupleParallelRetriever()
        self._reasoner = reasoner or ReasonerReranker()

    def search(
        self,
        query: str,
        items: list[MemoryStoreItem],
        top_k: int = 5,
    ) -> QuadrupleRetrievalReport:
        """Execute the full goal-driven quadruple parallel retrieval and semantic reasoner pipeline."""
        start_time = time.perf_counter()

        # Step 1: Pre-retrieval TaskGoalParser deconstruction
        parsed_goal = self._parser.parse_query(query)

        # Step 2: Quadruple parallel recall & deduplicated fusion
        channel_results, fused_candidates = self._retriever.execute_recall(
            goal=parsed_goal,
            items=items,
            top_k=max(15, top_k * 3),
        )

        # Step 3: Reasoner semantic inference reranking
        final_hits: list[RerankedMemoryHit] = self._reasoner.rerank_candidates(
            goal=parsed_goal,
            candidates=fused_candidates,
            top_k=top_k,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        channel_counts = {
            channel.value: len(hits)
            for channel, hits in channel_results.items()
        }

        return QuadrupleRetrievalReport(
            query=query,
            parsed_goal=parsed_goal,
            channel_hits_count=channel_counts,
            fused_candidates_count=len(fused_candidates),
            final_hits=final_hits,
            latency_ms=round(elapsed_ms, 2),
        )
