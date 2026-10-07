"""[POS]: src/myrm_agent_harness/toolkits/memory/cognitive_box/service.py
[INPUT]: Database configuration, candidate strings, and FourLayerCognitiveMemoryBox storage.
[OUTPUT]: CognitiveMemoryBoxService providing unified intake screening and cognitive layer management.
"""

import time
import uuid
from pathlib import Path

from myrm_agent_harness.toolkits.memory.cognitive_box.box import (
    FourLayerCognitiveMemoryBox,
)
from myrm_agent_harness.toolkits.memory.cognitive_box.intake_filter import (
    StrictMemoryIntakeFilter,
)
from myrm_agent_harness.toolkits.memory.cognitive_box.models import (
    CognitiveBoxSnapshot,
    CognitiveLayerKind,
    CognitiveMemoryEntry,
    IntakeDecisionKind,
    IntakeEvaluationReport,
)


class CognitiveMemoryBoxService:
    """Unified service orchestrating intake filtering and partitioned cognitive persistence."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._box = FourLayerCognitiveMemoryBox(db_path=db_path)

    @property
    def box(self) -> FourLayerCognitiveMemoryBox:
        return self._box

    def evaluate_and_ingest(
        self,
        raw_content: str,
        source_session: str | None = None,
        forced_layer: CognitiveLayerKind | None = None,
        tags: list[str] | None = None,
    ) -> tuple[IntakeEvaluationReport, CognitiveMemoryEntry | None]:
        """Screen content through StrictMemoryIntakeFilter and admit if high-value."""
        existing = self._box.list_entries(limit=300)
        report = StrictMemoryIntakeFilter.evaluate(
            raw_content=raw_content,
            existing_entries=existing,
            forced_layer=forced_layer,
        )

        entry_tags = list(tags) if tags else []

        if report.decision == IntakeDecisionKind.ADMIT:
            assert report.layer is not None
            entry_id = f"cog_{uuid.uuid4().hex[:12]}"
            entry = CognitiveMemoryEntry(
                id=entry_id,
                layer=report.layer,
                content=report.sanitized_content,
                confidence=report.confidence,
                tags=entry_tags,
                source_session=source_session,
            )
            saved = self._box.write_entry(entry)
            return report, saved

        if report.decision == IntakeDecisionKind.UPDATE_EXISTING:
            assert report.layer is not None
            target_id = report.existing_entry_id or f"cog_{uuid.uuid4().hex[:12]}"
            existing_item = self._box.get_entry(target_id)
            created_at = existing_item.created_at if existing_item else time.time()
            combined_tags = list(set((existing_item.tags if existing_item else []) + entry_tags))

            updated_entry = CognitiveMemoryEntry(
                id=target_id,
                layer=report.layer,
                content=report.sanitized_content,
                confidence=max(report.confidence, existing_item.confidence if existing_item else 0.8),
                tags=combined_tags,
                created_at=created_at,
                updated_at=time.time(),
                source_session=source_session,
            )
            saved = self._box.write_entry(updated_entry)
            return report, saved

        return report, None

    def write_direct_entry(self, entry: CognitiveMemoryEntry) -> CognitiveMemoryEntry:
        """Write an entry directly (e.g. for system identity or environment setup)."""
        return self._box.write_entry(entry)

    def get_entries(
        self,
        layer: CognitiveLayerKind | None = None,
        limit: int = 100,
    ) -> list[CognitiveMemoryEntry]:
        """List cognitive entries."""
        return self._box.list_entries(layer=layer, limit=limit)

    def get_snapshot(self) -> CognitiveBoxSnapshot:
        """Obtain snapshot of all four cognitive layers."""
        return self._box.get_snapshot()

    def clear_layer(self, layer: CognitiveLayerKind) -> int:
        """Purge all entries in a specific layer."""
        return self._box.clear_layer(layer)

    def render_prompt_context(self) -> str:
        """Render cognitive context block for prompt injection."""
        return self._box.render_prompt_context()

    def close(self) -> None:
        """Close database resources."""
        self._box.close()
