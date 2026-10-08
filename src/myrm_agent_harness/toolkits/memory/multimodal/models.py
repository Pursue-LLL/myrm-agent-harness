"""Domain models and contracts for multimodal vision and sandbox artifact long-term memory.

[INPUT]
- None (standard library only)

[OUTPUT]
- AssetModality: Enum categorizing multimodal asset modality.
- ArtifactKind: Enum categorizing sandbox artifact and vision asset type.
- MultimodalMemoryItem: Core domain record for vision asset or sandbox artifact.
- MultimodalIngestRequest: Payload for ingesting a multimodal item.
- MultimodalSearchQuery: Query specification for cross-modal search.
- MultimodalSearchHit: Ranked hit with rich card preview representation.

[POS]
Data contracts of the multimodal memory package; the other modules of the package build on these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class AssetModality(StrEnum):
    """Categorical modality of the stored memory asset."""

    IMAGE = "image"
    ARTIFACT = "artifact"
    HYBRID = "hybrid"


class ArtifactKind(StrEnum):
    """Specific structural kind of vision asset or sandbox artifact."""

    DIAGRAM = "diagram"
    CHART = "chart"
    REPORT_HTML = "report_html"
    DATA_SHEET = "data_sheet"
    SOURCE_CODE = "source_code"
    GENERIC_FILE = "generic_file"


@dataclass(frozen=True, slots=True)
class MultimodalMemoryItem:
    """Core domain record representing a long-term multimodal or artifact memory item."""

    item_id: str
    modality: AssetModality
    artifact_kind: ArtifactKind
    title: str
    description: str
    mime_type: str
    visual_summary: str | None = None
    file_path: str | None = None
    tags: list[str] = field(default_factory=list)
    session_id: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MultimodalIngestRequest:
    """Input specification for ingesting a vision asset or sandbox artifact into memory."""

    title: str
    description: str
    modality: AssetModality = AssetModality.ARTIFACT
    artifact_kind: ArtifactKind = ArtifactKind.GENERIC_FILE
    visual_summary: str | None = None
    file_path: str | None = None
    mime_type: str = "application/octet-stream"
    tags: list[str] = field(default_factory=list)
    session_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MultimodalSearchQuery:
    """Cross-modal search parameters."""

    query_text: str
    modality_filter: AssetModality | None = None
    artifact_kind_filter: ArtifactKind | None = None
    session_id: str | None = None
    limit: int = 10


@dataclass(frozen=True, slots=True)
class MultimodalSearchHit:
    """Ranked hit from cross-modal retrieval with UI card projection."""

    item: MultimodalMemoryItem
    relevance_score: float
    matched_modality: AssetModality
    card_preview: dict[str, str] = field(default_factory=dict)
