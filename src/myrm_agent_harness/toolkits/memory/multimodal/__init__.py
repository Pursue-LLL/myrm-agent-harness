"""Multimodal vision and sandbox artifact memory package.

[INPUT]
- memory.multimodal.orchestrator::MultimodalMemoryOrchestrator (POS: Entry point of the multimodal memory package)
- memory.multimodal.extractor::MultimodalFeatureExtractor (POS: Ingest-side feature extraction of the multimodal memory package)
- memory.multimodal.store::MultimodalMemoryStore (POS: Storage layer of the multimodal memory package)
- memory.multimodal.retriever::CrossModalRetriever (POS: Search layer of the multimodal memory package)
- memory.multimodal.models::{ArtifactKind, AssetModality, MultimodalIngestRequest, MultimodalMemoryItem, MultimodalSearchHit, MultimodalSearchQuery} (POS: Data contracts of the multimodal memory package)

[OUTPUT]
- MultimodalMemoryOrchestrator, MultimodalFeatureExtractor, MultimodalMemoryStore, CrossModalRetriever: facade and the components behind it
- ArtifactKind, AssetModality, MultimodalIngestRequest, MultimodalMemoryItem, MultimodalSearchHit, MultimodalSearchQuery: data contracts

[POS]
Package facade of the multimodal memory suite; re-exports its contracts, components and orchestrator.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.multimodal.extractor import (
    MultimodalFeatureExtractor,
)
from myrm_agent_harness.toolkits.memory.multimodal.models import (
    ArtifactKind,
    AssetModality,
    MultimodalIngestRequest,
    MultimodalMemoryItem,
    MultimodalSearchHit,
    MultimodalSearchQuery,
)
from myrm_agent_harness.toolkits.memory.multimodal.orchestrator import (
    MultimodalMemoryOrchestrator,
)
from myrm_agent_harness.toolkits.memory.multimodal.retriever import (
    CrossModalRetriever,
)
from myrm_agent_harness.toolkits.memory.multimodal.store import (
    MultimodalMemoryStore,
)

__all__ = [
    "ArtifactKind",
    "AssetModality",
    "CrossModalRetriever",
    "MultimodalFeatureExtractor",
    "MultimodalIngestRequest",
    "MultimodalMemoryItem",
    "MultimodalMemoryOrchestrator",
    "MultimodalMemoryStore",
    "MultimodalSearchHit",
    "MultimodalSearchQuery",
]
