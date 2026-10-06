"""Unified facade engine for zero-LLM local memory capture and FTS graph retrieval.

Combines deterministic rule-based fact extraction, SQLite FTS5 lexical matching,
and 1-hop [[Wikilink]] graph traversal under a coherent zero-cost API.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading
from pathlib import Path

from myrm_agent_harness.toolkits.memory.zero_llm.fts_graph_retriever import (
    ZeroLlmFtsGraphRetriever,
)
from myrm_agent_harness.toolkits.memory.zero_llm.progressive_gate import (
    ZeroLlmProgressiveGate,
)
from myrm_agent_harness.toolkits.memory.zero_llm.rule_extractor import (
    ZeroLlmRuleExtractor,
)
from myrm_agent_harness.toolkits.memory.zero_llm.types import (
    ExtractionBatchResult,
    ZeroLlmConfig,
    ZeroLlmSearchResult,
)


class ZeroLlmMemoryEngine:
    """Unified engine coordinating zero-cost capture and FTS5 graph search."""

    def __init__(
        self,
        db_path: Path | str,
        config: ZeroLlmConfig | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.config = config or ZeroLlmConfig()
        self._lock = threading.RLock()

        self.extractor = ZeroLlmRuleExtractor(min_confidence=self.config.min_confidence)
        self.retriever = ZeroLlmFtsGraphRetriever(
            db_path=self.db_path,
            limit=self.config.fts_limit,
            graph_hop_decay=self.config.graph_hop_decay,
        )
        self.gate = ZeroLlmProgressiveGate(config=self.config)

        self._total_extractions: int = 0
        self._total_queries: int = 0

    def extract_facts(
        self,
        text: str,
        turn_index: int = 0,
        source_file: str | None = None,
    ) -> ExtractionBatchResult:
        """Extract high-signal facts deterministically with zero model tokens."""
        with self._lock:
            raw_facts = self.extractor.extract_from_text(
                text=text,
                turn_index=turn_index,
                source_file=source_file,
            )
            consolidated = self.gate.consolidate_facts(
                deterministic_facts=raw_facts,
                turn_index=turn_index,
            )
            self._total_extractions += len(consolidated)
            return ExtractionBatchResult(
                facts=consolidated,
                total_extracted=len(consolidated),
                turn_count=1,
                zero_token_cost=True,
            )

    def search(
        self,
        query: str,
        profile_id: str | None = None,
    ) -> ZeroLlmSearchResult:
        """Search memory pages and linked entities with FTS5 and graph traversal."""
        with self._lock:
            self._total_queries += 1
            return self.retriever.search(query=query, profile_id=profile_id)

    def get_stats(self) -> dict[str, int | float | str | bool]:
        """Return engine operational telemetry and cost verification markers."""
        with self._lock:
            return {
                "total_extractions": self._total_extractions,
                "total_queries": self._total_queries,
                "zero_token_cost": True,
                "augmentation_mode": self.config.augmentation_mode.value,
                "llm_available": self.gate.is_llm_available(),
                "min_confidence": self.config.min_confidence,
                "graph_hop_decay": self.config.graph_hop_decay,
            }
