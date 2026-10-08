"""Orchestrator unifying multimodal asset ingestion, indexing, and cross-modal search.

[INPUT]
- memory.multimodal.models::{MultimodalIngestRequest, MultimodalMemoryItem, MultimodalSearchQuery, MultimodalSearchHit} (POS: data contracts of the multimodal memory package)
- memory.multimodal.extractor::MultimodalFeatureExtractor (POS: ingest-side feature extraction and UI card previews)
- memory.multimodal.store::MultimodalMemoryStore (POS: in-memory repository of multimodal memory items)
- memory.multimodal.retriever::CrossModalRetriever (POS: lexical cross-modal search layer)

[OUTPUT]
- MultimodalMemoryOrchestrator: Facade with ingest_asset, search_assets, get_asset, get_asset_card and clear

[POS]
Entry point of the multimodal memory package; composes extractor, store and retriever behind one facade.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.multimodal.extractor import (
    MultimodalFeatureExtractor,
)
from myrm_agent_harness.toolkits.memory.multimodal.models import (
    MultimodalIngestRequest,
    MultimodalMemoryItem,
    MultimodalSearchHit,
    MultimodalSearchQuery,
)
from myrm_agent_harness.toolkits.memory.multimodal.retriever import (
    CrossModalRetriever,
)
from myrm_agent_harness.toolkits.memory.multimodal.store import (
    MultimodalMemoryStore,
)


class MultimodalMemoryOrchestrator:
    """Facade orchestrating long-term multimodal memory ingestion and cross-modal retrieval."""

    def __init__(
        self,
        store: MultimodalMemoryStore | None = None,
        extractor: MultimodalFeatureExtractor | None = None,
        retriever: CrossModalRetriever | None = None,
    ) -> None:
        self.store = store or MultimodalMemoryStore()
        self.extractor = extractor or MultimodalFeatureExtractor()
        self.retriever = retriever or CrossModalRetriever(extractor=self.extractor)

    def ingest_asset(self, request: MultimodalIngestRequest) -> MultimodalMemoryItem:
        """Ingest, extract features, and index a vision asset or sandbox artifact."""
        item = self.extractor.extract_item(request)
        self.store.add(item)
        return item

    def search_assets(self, query: MultimodalSearchQuery) -> list[MultimodalSearchHit]:
        """Perform cross-modal semantic search against stored vision assets and artifacts."""
        return self.retriever.search(query, self.store)

    def get_asset(self, item_id: str) -> MultimodalMemoryItem | None:
        """Retrieve indexed multimodal item by ID."""
        return self.store.get(item_id)

    def get_asset_card(self, item_id: str) -> dict[str, str] | None:
        """Retrieve presentation card metadata for an indexed asset."""
        item = self.store.get(item_id)
        if item is None:
            return None
        return self.extractor.build_card_preview(item)

    def clear(self) -> None:
        """Clear all indexed multimodal items."""
        self.store.clear()
