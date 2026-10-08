"""Multimodal vision and sandbox artifact memory package.

[INPUT]
- memory.multimodal.{models, extractor, store, retriever, orchestrator} (POS: contracts, extraction, storage, search and facade of multimodal memory)

[OUTPUT]
- Public contracts, components and orchestrator for multimodal memory and artifact retrieval.

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
