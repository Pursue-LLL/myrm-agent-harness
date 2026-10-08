"""Feature extractor for multimodal vision assets and sandbox artifacts.

[INPUT]
- memory.multimodal.models::{MultimodalIngestRequest, MultimodalMemoryItem, AssetModality, ArtifactKind} (POS: Data contracts of the multimodal memory package)

[OUTPUT]
- MultimodalFeatureExtractor: Builds a populated MultimodalMemoryItem from an ingest request (modality, artifact kind and MIME type taken from the file extension when left at defaults, derived tags) and projects an item into a UI card preview

[POS]
Ingest-side feature extraction of the multimodal memory package; the orchestrator uses it to create items and the retriever to build hit previews.
"""

from __future__ import annotations

import os
import uuid

from myrm_agent_harness.toolkits.memory.multimodal.models import (
    ArtifactKind,
    AssetModality,
    MultimodalIngestRequest,
    MultimodalMemoryItem,
)

_EXTENSION_TO_KIND: dict[str, tuple[AssetModality, ArtifactKind, str]] = {
    ".png": (AssetModality.IMAGE, ArtifactKind.DIAGRAM, "image/png"),
    ".jpg": (AssetModality.IMAGE, ArtifactKind.DIAGRAM, "image/jpeg"),
    ".jpeg": (AssetModality.IMAGE, ArtifactKind.DIAGRAM, "image/jpeg"),
    ".webp": (AssetModality.IMAGE, ArtifactKind.DIAGRAM, "image/webp"),
    ".svg": (AssetModality.IMAGE, ArtifactKind.DIAGRAM, "image/svg+xml"),
    ".html": (AssetModality.ARTIFACT, ArtifactKind.REPORT_HTML, "text/html"),
    ".csv": (AssetModality.ARTIFACT, ArtifactKind.DATA_SHEET, "text/csv"),
    ".json": (AssetModality.ARTIFACT, ArtifactKind.DATA_SHEET, "application/json"),
    ".py": (AssetModality.ARTIFACT, ArtifactKind.SOURCE_CODE, "text/x-python"),
    ".rs": (AssetModality.ARTIFACT, ArtifactKind.SOURCE_CODE, "text/x-rust"),
    ".md": (AssetModality.ARTIFACT, ArtifactKind.REPORT_HTML, "text/markdown"),
}


class MultimodalFeatureExtractor:
    """Extracts structural features, modalities, and card representations for memory assets."""

    def extract_item(
        self,
        request: MultimodalIngestRequest,
        item_id: str | None = None,
    ) -> MultimodalMemoryItem:
        """Transform ingest request into fully populated MultimodalMemoryItem."""
        actual_id = item_id or f"mm_{uuid.uuid4().hex[:12]}"

        # Infer modality and artifact kind if not explicitly specified
        inferred_modality = request.modality
        inferred_kind = request.artifact_kind
        inferred_mime = request.mime_type

        if request.file_path:
            ext = os.path.splitext(request.file_path)[1].lower()
            if ext in _EXTENSION_TO_KIND:
                kind_mod, kind_type, mime = _EXTENSION_TO_KIND[ext]
                if request.modality == AssetModality.ARTIFACT and kind_mod == AssetModality.IMAGE:
                    inferred_modality = kind_mod
                if request.artifact_kind == ArtifactKind.GENERIC_FILE:
                    inferred_kind = kind_type
                if request.mime_type == "application/octet-stream":
                    inferred_mime = mime

        # Assemble extracted tags
        tags = set(request.tags)
        tags.add(inferred_modality.value)
        tags.add(inferred_kind.value)
        if request.session_id:
            tags.add(f"session:{request.session_id}")

        return MultimodalMemoryItem(
            item_id=actual_id,
            modality=inferred_modality,
            artifact_kind=inferred_kind,
            title=request.title.strip(),
            description=request.description.strip(),
            visual_summary=request.visual_summary,
            file_path=request.file_path,
            mime_type=inferred_mime,
            tags=sorted(tags),
            session_id=request.session_id,
            metadata=dict(request.metadata),
        )

    def build_card_preview(self, item: MultimodalMemoryItem) -> dict[str, str]:
        """Construct presentation card metadata for UI and conversational context."""
        summary_text = item.visual_summary or item.description
        path_status = "available" if item.file_path else "virtual_asset"

        return {
            "item_id": item.item_id,
            "title": item.title,
            "modality": item.modality.value,
            "artifact_kind": item.artifact_kind.value,
            "summary": summary_text[:200],
            "file_path": item.file_path or "",
            "path_status": path_status,
            "mime_type": item.mime_type,
            "created_at": item.created_at,
        }
