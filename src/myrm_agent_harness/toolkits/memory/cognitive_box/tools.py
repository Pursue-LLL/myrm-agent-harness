"""[POS]: src/myrm_agent_harness/toolkits/memory/cognitive_box/tools.py
[INPUT]: CognitiveMemoryBoxService and runtime parameters.
[OUTPUT]: CognitiveBoxMetaTools exposing agent meta-tools for cognitive layers and lesson crystallization.
"""

from myrm_agent_harness.toolkits.memory.cognitive_box.models import (
    CognitiveLayerKind,
    IntakeDecisionKind,
)
from myrm_agent_harness.toolkits.memory.cognitive_box.service import (
    CognitiveMemoryBoxService,
)


class CognitiveBoxMetaTools:
    """Agent-facing meta-tools to inspect cognitive layers and distill durable lessons."""

    def __init__(self, service: CognitiveMemoryBoxService) -> None:
        self._service = service

    def query_cognitive_box(
        self,
        layer: str | None = None,
    ) -> list[dict[str, str | float]]:
        """Query active entries in the cognitive box."""
        target_layer = CognitiveLayerKind(layer) if layer else None
        entries = self._service.get_entries(layer=target_layer, limit=50)
        return [
            {
                "id": entry.id,
                "layer": entry.layer.value,
                "content": entry.content,
                "confidence": entry.confidence,
                "updated_at": entry.updated_at,
            }
            for entry in entries
        ]

    def crystallize_lesson(
        self,
        lesson: str,
        tags: list[str] | None = None,
        session_id: str | None = None,
    ) -> dict[str, str | float | bool]:
        """Submit a lesson or architectural rule to the strict cognitive intake filter."""
        report, entry = self._service.evaluate_and_ingest(
            raw_content=lesson,
            source_session=session_id,
            forced_layer=CognitiveLayerKind.LESSONS_RULES,
            tags=tags,
        )
        is_admitted = report.decision in (
            IntakeDecisionKind.ADMIT,
            IntakeDecisionKind.UPDATE_EXISTING,
        )
        return {
            "admitted": is_admitted,
            "decision": report.decision.value,
            "reason": report.reason,
            "entry_id": entry.id if entry else "",
            "confidence": report.confidence,
        }
