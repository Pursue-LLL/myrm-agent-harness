"""Cross-modal semantic retriever for natural language search over vision and artifact memory.

[INPUT]
- query: MultimodalSearchQuery
- store: MultimodalMemoryStore

[OUTPUT]
- list[MultimodalSearchHit]: Ranked cross-modal retrieval hits with UI card projection

[POS]
myrm_agent_harness.toolkits.memory.multimodal.retriever
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.multimodal.extractor import (
    MultimodalFeatureExtractor,
)
from myrm_agent_harness.toolkits.memory.multimodal.models import (
    MultimodalMemoryItem,
    MultimodalSearchHit,
    MultimodalSearchQuery,
)
from myrm_agent_harness.toolkits.memory.multimodal.store import (
    MultimodalMemoryStore,
)


class CrossModalRetriever:
    """Performs cross-modal semantic matching from natural language query to multimodal items."""

    def __init__(
        self,
        extractor: MultimodalFeatureExtractor | None = None,
    ) -> None:
        self.extractor = extractor or MultimodalFeatureExtractor()

    def search(
        self,
        query: MultimodalSearchQuery,
        store: MultimodalMemoryStore,
    ) -> list[MultimodalSearchHit]:
        """Execute cross-modal search against indexed items in store."""
        cleaned_query = query.query_text.strip().lower()
        if not cleaned_query:
            return []

        candidates: Sequence[MultimodalMemoryItem] = store.list_all(
            session_id=query.session_id,
            modality=query.modality_filter,
        )

        query_tokens = self._tokenize(cleaned_query)
        scored_hits: list[MultimodalSearchHit] = []

        for item in candidates:
            # Check artifact_kind filter if specified
            if (
                query.artifact_kind_filter is not None
                and item.artifact_kind != query.artifact_kind_filter
            ):
                continue

            score = self._compute_relevance(cleaned_query, query_tokens, item)
            if score > 0.1:
                card = self.extractor.build_card_preview(item)
                scored_hits.append(
                    MultimodalSearchHit(
                        item=item,
                        relevance_score=round(score, 3),
                        matched_modality=item.modality,
                        card_preview=card,
                    )
                )

        # Sort descending by relevance score
        scored_hits.sort(key=lambda hit: hit.relevance_score, reverse=True)
        return scored_hits[: query.limit]

    def _tokenize(self, text: str) -> list[str]:
        tokens = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text)
        return [t.lower() for t in tokens if len(t.strip()) > 0]

    def _compute_relevance(
        self,
        raw_query: str,
        query_tokens: list[str],
        item: MultimodalMemoryItem,
    ) -> float:
        title_lower = item.title.lower()
        desc_lower = item.description.lower()
        summary_lower = (item.visual_summary or "").lower()

        # 1. Exact phrase match in title (strongest signal)
        if raw_query in title_lower:
            return 1.0

        # 2. Exact phrase match in summary or description
        if raw_query in summary_lower or raw_query in desc_lower:
            return 0.85

        if not query_tokens:
            return 0.0

        # 3. Token overlap scoring across title, summary, description, and tags
        title_score = sum(1 for t in query_tokens if t in title_lower) / len(query_tokens)
        summary_score = (
            sum(1 for t in query_tokens if t in summary_lower) / len(query_tokens)
            if summary_lower
            else 0.0
        )
        desc_score = sum(1 for t in query_tokens if t in desc_lower) / len(query_tokens)

        # Tag overlap
        tag_str = " ".join(item.tags).lower()
        tag_score = sum(1 for t in query_tokens if t in tag_str) / len(query_tokens)

        combined = (
            0.45 * title_score
            + 0.30 * summary_score
            + 0.15 * desc_score
            + 0.10 * tag_score
        )
        return min(combined, 0.95)
