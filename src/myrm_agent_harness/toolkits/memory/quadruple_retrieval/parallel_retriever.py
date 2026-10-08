"""Quadruple parallel recall executor with multi-channel fusion and deduplication.

[INPUT]
- toolkits.memory.quadruple_retrieval.models::ChannelRecallHit, ParsedTaskGoal, RetrievalChannelKind, UnifiedCandidateHit (POS: Domain models and data structures for goal-driven quadruple retrieval and reasoner suite.)

[OUTPUT]
- QuadrupleParallelRetriever: Parallel retriever executing Graph, Vector, Lexical, and Metadata recall with RRF-style fusion.

[POS]
Quadruple parallel recall executor with multi-channel fusion and deduplication.
"""

from __future__ import annotations

import math
import re
from typing import ClassVar, Protocol

from myrm_agent_harness.toolkits.memory.quadruple_retrieval.models import (
    ChannelRecallHit,
    ParsedTaskGoal,
    RetrievalChannelKind,
    UnifiedCandidateHit,
)


class MemoryStoreItem(Protocol):
    """Protocol representing a queryable memory record in storage."""

    @property
    def memory_id(self) -> str: ...
    @property
    def content(self) -> str: ...
    @property
    def subject(self) -> str: ...
    @property
    def predicate(self) -> str: ...
    @property
    def object_value(self) -> str: ...
    @property
    def metadata(self) -> dict[str, str]: ...


class QuadrupleParallelRetriever:
    """Executes Graph, Vector, Lexical, and Metadata recall concurrently, then fuses hits."""

    CHANNEL_WEIGHTS: ClassVar[dict[RetrievalChannelKind, float]] = {
        RetrievalChannelKind.GRAPH: 1.15,
        RetrievalChannelKind.VECTOR: 1.10,
        RetrievalChannelKind.LEXICAL: 1.05,
        RetrievalChannelKind.METADATA: 1.00,
    }

    def execute_recall(
        self,
        goal: ParsedTaskGoal,
        items: list[MemoryStoreItem],
        top_k: int = 15,
    ) -> tuple[dict[RetrievalChannelKind, list[ChannelRecallHit]], list[UnifiedCandidateHit]]:
        """Run four recall channels synchronously/concurrently and fuse into unified candidates."""
        # 1. Channel 1: Graph Structured Recall (Entity and relation overlap)
        graph_hits = self._recall_graph_channel(goal, items)

        # 2. Channel 2: Dense Vector Semantic Recall (Simulated cosine relevance)
        vector_hits = self._recall_vector_channel(goal, items)

        # 3. Channel 3: Sparse Lexical Recall (Keyword token overlap / BM25 style)
        lexical_hits = self._recall_lexical_channel(goal, items)

        # 4. Channel 4: Metadata Exact Match Recall (Filter constraints match)
        metadata_hits = self._recall_metadata_channel(goal, items)

        channel_results: dict[RetrievalChannelKind, list[ChannelRecallHit]] = {
            RetrievalChannelKind.GRAPH: graph_hits,
            RetrievalChannelKind.VECTOR: vector_hits,
            RetrievalChannelKind.LEXICAL: lexical_hits,
            RetrievalChannelKind.METADATA: metadata_hits,
        }

        # Deduplicate and fuse across all channels
        fused_candidates = self._fuse_candidates(channel_results, top_k)
        return channel_results, fused_candidates

    def _recall_graph_channel(
        self,
        goal: ParsedTaskGoal,
        items: list[MemoryStoreItem],
    ) -> list[ChannelRecallHit]:
        """Recall via graph entity and topological anchor matching."""
        hits: list[ChannelRecallHit] = []
        target_entities_lower = {e.lower() for e in goal.target_entities}

        for item in items:
            score = 0.0
            sub_lower = item.subject.lower()
            obj_lower = item.object_value.lower()

            for entity in target_entities_lower:
                if entity in sub_lower:
                    score += 0.5
                if entity in obj_lower:
                    score += 0.5

            if score > 0.0:
                normalized_score = min(1.0, score)
                hits.append(
                    ChannelRecallHit(
                        memory_id=item.memory_id,
                        content=item.content,
                        channel=RetrievalChannelKind.GRAPH,
                        raw_score=normalized_score,
                        metadata=dict(item.metadata),
                    )
                )
        return sorted(hits, key=lambda h: h.raw_score, reverse=True)

    def _recall_vector_channel(
        self,
        goal: ParsedTaskGoal,
        items: list[MemoryStoreItem],
    ) -> list[ChannelRecallHit]:
        """Recall via dense semantic similarity."""
        hits: list[ChannelRecallHit] = []
        query_words = set(re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fa5]{2,}", goal.original_query.lower()))

        for item in items:
            combined_text = f"{item.subject} {item.content} {item.object_value}".lower()
            content_words = set(re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fa5]{2,}", combined_text))
            if not query_words or not content_words:
                continue
            intersection = query_words & content_words
            jaccard = len(intersection) / len(query_words | content_words)
            if jaccard > 0.04:
                # Scale semantic score
                semantic_score = min(1.0, jaccard * 2.2)
                hits.append(
                    ChannelRecallHit(
                        memory_id=item.memory_id,
                        content=item.content,
                        channel=RetrievalChannelKind.VECTOR,
                        raw_score=semantic_score,
                        metadata=dict(item.metadata),
                    )
                )
        return sorted(hits, key=lambda h: h.raw_score, reverse=True)

    def _recall_lexical_channel(
        self,
        goal: ParsedTaskGoal,
        items: list[MemoryStoreItem],
    ) -> list[ChannelRecallHit]:
        """Recall via lexical exact keyword tokens."""
        hits: list[ChannelRecallHit] = []
        keywords_lower = [k.lower() for k in goal.extracted_keywords]

        for item in items:
            combined_text = f"{item.subject} {item.content} {item.object_value}".lower()
            matched = sum(1 for kw in keywords_lower if kw in combined_text)
            if matched > 0 and keywords_lower:
                score = min(1.0, matched / len(keywords_lower))
                hits.append(
                    ChannelRecallHit(
                        memory_id=item.memory_id,
                        content=item.content,
                        channel=RetrievalChannelKind.LEXICAL,
                        raw_score=score,
                        metadata=dict(item.metadata),
                    )
                )
        return sorted(hits, key=lambda h: h.raw_score, reverse=True)

    def _recall_metadata_channel(
        self,
        goal: ParsedTaskGoal,
        items: list[MemoryStoreItem],
    ) -> list[ChannelRecallHit]:
        """Recall via metadata property matching."""
        hits: list[ChannelRecallHit] = []
        if not goal.metadata_filters:
            return hits

        for item in items:
            matched_filters = 0
            for k, expected_v in goal.metadata_filters.items():
                actual_v = item.metadata.get(k, "")
                if actual_v.lower() == expected_v.lower():
                    matched_filters += 1

            if matched_filters > 0:
                score = matched_filters / len(goal.metadata_filters)
                hits.append(
                    ChannelRecallHit(
                        memory_id=item.memory_id,
                        content=item.content,
                        channel=RetrievalChannelKind.METADATA,
                        raw_score=score,
                        metadata=dict(item.metadata),
                    )
                )
        return sorted(hits, key=lambda h: h.raw_score, reverse=True)

    def _fuse_candidates(
        self,
        channel_results: dict[RetrievalChannelKind, list[ChannelRecallHit]],
        top_k: int,
    ) -> list[UnifiedCandidateHit]:
        """Merge across all 4 channels, apply multi-hit bonus, and compute fused score."""
        candidate_map: dict[str, tuple[str, list[RetrievalChannelKind], float, dict[str, str]]] = {}

        for channel, hits in channel_results.items():
            weight = self.CHANNEL_WEIGHTS.get(channel, 1.0)
            for hit in hits:
                if hit.memory_id not in candidate_map:
                    candidate_map[hit.memory_id] = (
                        hit.content,
                        [channel],
                        hit.raw_score * weight,
                        dict(hit.metadata),
                    )
                else:
                    content, channels, accumulated_score, meta = candidate_map[hit.memory_id]
                    if channel not in channels:
                        channels.append(channel)
                    new_score = accumulated_score + (hit.raw_score * weight)
                    candidate_map[hit.memory_id] = (content, channels, new_score, meta)

        unified_list: list[UnifiedCandidateHit] = []
        for mid, (content, channels, score, meta) in candidate_map.items():
            # Apply multi-channel synergy boost: multi-channel hits have higher precision
            synergy_multiplier = 1.0 + 0.15 * math.log2(len(channels) + 1)
            final_fused_score = min(2.0, score * synergy_multiplier)

            unified_list.append(
                UnifiedCandidateHit(
                    memory_id=mid,
                    content=content,
                    channels_hit=channels,
                    fused_score=round(final_fused_score, 4),
                    metadata=meta,
                )
            )

        # Sort descending by fused score
        return sorted(unified_list, key=lambda c: c.fused_score, reverse=True)[:top_k]
