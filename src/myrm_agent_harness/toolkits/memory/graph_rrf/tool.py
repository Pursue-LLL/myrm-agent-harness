"""Agent-facing LangChain tool for dual-channel Knowledge Graph and Vector RRF memory retrieval.

[INPUT]
- toolkits.memory.graph_rrf.dual_channel_retriever::DualChannelRRFRetriever (POS: Dual-channel search coordinator)
- toolkits.memory.graph_rrf.types::FusedMemoryHit (POS: Unified search hit data model)

[OUTPUT]
- HybridGraphRRFSearchInput: Pydantic input schema for LangChain tool
- create_graph_rrf_search_tool: Factory creating LangChain BaseTool for Agent runtime

[POS]
Agent-facing LangChain tool for dual-channel Knowledge Graph and Vector RRF memory retrieval.
"""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.graph_rrf.dual_channel_retriever import (
    DualChannelRRFRetriever,
)


class HybridGraphRRFSearchInput(BaseModel):
    """Input schema for hybrid knowledge graph and vector RRF search."""

    query: str = Field(
        description="Search query describing the fact, concept, or multi-hop entity relation to recall"
    )
    seed_entity_names: list[str] = Field(
        default_factory=list,
        description="Optional list of seed entity names to anchor and traverse in knowledge graph",
    )
    top_k: int = Field(
        default=5,
        description="Number of fused top ranked memories to return",
    )


def create_graph_rrf_search_tool(retriever: DualChannelRRFRetriever) -> BaseTool:
    """Create a LangChain standard tool for agents to recall memories via graph-vector RRF."""

    @tool("search_hybrid_knowledge_graph", args_schema=HybridGraphRRFSearchInput)
    def search_hybrid_knowledge_graph(
        query: str,
        seed_entity_names: list[str] | None = None,
        top_k: int = 5,
    ) -> str:
        """Recall long-term memories using hybrid knowledge graph topology and semantic vector RRF fusion."""
        fused_hits = retriever.search(
            query=query,
            seed_entity_names=seed_entity_names if seed_entity_names else None,
            top_k=top_k,
        )

        hits_data: list[dict[str, str | int | float | list[str]]] = []
        for h in fused_hits:
            hits_data.append(
                {
                    "memory_id": h.memory_id,
                    "content": h.content,
                    "fused_score": round(h.fused_score, 4),
                    "vector_rank": h.vector_rank if h.vector_rank is not None else 0,
                    "graph_rank": h.graph_rank if h.graph_rank is not None else 0,
                    "hit_sources": h.hit_sources,
                    "explanation": h.explanation,
                }
            )

        output = {
            "query": query,
            "total_hits": len(hits_data),
            "fused_hits": hits_data,
        }
        return json.dumps(output, ensure_ascii=False)

    return search_hybrid_knowledge_graph
