"""[POS]: src/myrm_agent_harness/toolkits/memory/ingestion_gateway/gateway.py
[INPUT]: ContextIngestionPayload holding multi-source raw transcripts or audio recorder data.
[OUTPUT]: UniversalContextIngestionGateway coordinating deduplication, parsing, distillation, and indexing.
"""

import time
from pathlib import Path

from .dedup import IngestionIdempotencyGuard
from .distiller import VoiceContextDistiller
from .models import ContextIngestionPayload, IngestionDigestResult
from .parser import TranscriptUniversalParser


class UniversalContextIngestionGateway:
    """Universal ingestion gateway for hardware voice cards and multi-source contexts."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.parser = TranscriptUniversalParser()
        self.guard = IngestionIdempotencyGuard(db_path=db_path)
        self.distiller = VoiceContextDistiller()

    def ingest(self, payload: ContextIngestionPayload) -> IngestionDigestResult:
        """Ingest raw audio transcript, parse format, distill content, and guard idempotency."""
        fingerprint = self.guard.compute_fingerprint(
            raw_payload=payload.raw_payload,
            device_id=payload.device_id,
        )

        now = time.time()
        # 1. Idempotency Check
        if self.guard.is_recorded(fingerprint):
            return IngestionDigestResult(
                fingerprint=fingerprint,
                title=payload.title,
                source_type=payload.source_type.value,
                speaker_count=0,
                segment_count=0,
                summary=f"Skipped duplicate ingestion for: {payload.title}",
                action_items=[],
                decisions=[],
                is_duplicate=True,
                created_at_epoch=now,
            )

        # 2. Universal Parsing
        raw_segments = self.parser.parse(payload)

        # 3. Distillation & Speaker Merging
        merged_segments = self.distiller.merge_adjacent_segments(raw_segments)
        speakers = sorted({seg.speaker for seg in merged_segments})
        action_items = self.distiller.extract_action_items(merged_segments)
        decisions = self.distiller.extract_decisions(merged_segments)
        summary = self.distiller.build_summary(
            title=payload.title,
            segments=merged_segments,
            distinct_speakers=speakers,
        )

        # 4. Record deduplication fingerprint
        self.guard.record_fingerprint(
            fingerprint=fingerprint,
            source_type=payload.source_type.value,
            device_id=payload.device_id,
            title=payload.title,
        )

        return IngestionDigestResult(
            fingerprint=fingerprint,
            title=payload.title,
            source_type=payload.source_type.value,
            speaker_count=len(speakers),
            segment_count=len(merged_segments),
            summary=summary,
            action_items=action_items,
            decisions=decisions,
            is_duplicate=False,
            created_at_epoch=now,
        )

    def list_history(self, limit: int = 50) -> list[dict[str, str | float]]:
        """List previously ingested context records."""
        return self.guard.list_records(limit=limit)

    def check_duplicate(self, raw_payload: str, device_id: str = "") -> bool:
        """Probe if payload is already registered."""
        fp = self.guard.compute_fingerprint(raw_payload=raw_payload, device_id=device_id)
        return self.guard.is_recorded(fp)

    def close(self) -> None:
        """Close underlying database connections."""
        self.guard.close()
