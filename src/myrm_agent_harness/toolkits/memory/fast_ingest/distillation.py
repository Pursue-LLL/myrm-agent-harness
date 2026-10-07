"""Asynchronous Deep Distillation Worker executing in idle cycles without user blocking.

[INPUT]
- toolkits.memory.fast_ingest.models::DistillationBatch, DistillationReport (POS: Data models for Sub-5%
  Latency One-Pass Fast Ingestion and Deep Distillation Engine.)
- toolkits.memory.fast_ingest.pipeline::FastMemoryCommitPipeline (POS: One-Pass Fast Memory Commit Pipeline
  with sub-5% latency overhead guarantee.)

[OUTPUT]
- AsyncDeepDistillationWorker: Consolidates fast-committed facts asynchronously during system idle cycles.

[POS]
Asynchronous Deep Distillation Worker executing in idle cycles without user blocking.
"""

import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from .models import (
    DistillationBatch,
    DistillationReport,
)
from .pipeline import FastMemoryCommitPipeline


class AsyncDeepDistillationWorker:
    """Consolidates fast-committed facts asynchronously during system idle cycles."""

    def __init__(self, deduplication_similarity_threshold: float = 0.85) -> None:
        """Initialize distillation worker with similarity clustering parameters."""
        self._similarity_threshold = deduplication_similarity_threshold
        self._distillation_history: list[DistillationReport] = []

    @property
    def history(self) -> list[DistillationReport]:
        """Return history of executed distillation batches."""
        return list(self._distillation_history)

    def distill_batch(self, batch: DistillationBatch) -> DistillationReport:
        """Execute deep distillation and deduplication on a batch of committed records.

        Args:
            batch: DistillationBatch containing un-distilled fast records.

        Returns:
            DistillationReport summarizing consolidated knowledge and compression ratio.
        """
        t_start = time.perf_counter()

        raw_facts: list[str] = []
        for r in batch.records:
            raw_facts.extend(r.extracted_facts)

        total_input = len(raw_facts)
        consolidated = self._consolidate_facts(raw_facts)
        dedup_count = total_input - len(consolidated)

        ratio = 0.0
        if total_input > 0:
            ratio = round(max(0.0, float(dedup_count) / float(total_input)), 3)

        duration_ms = (time.perf_counter() - t_start) * 1000.0

        report = DistillationReport(
            batch_id=batch.batch_id,
            input_record_count=len(batch.records),
            distilled_fact_count=len(consolidated),
            consolidated_facts=consolidated,
            deduplication_ratio=ratio,
            duration_ms=round(duration_ms, 3),
        )

        self._distillation_history.append(report)
        return report

    def run_idle_cycle(
        self,
        pipeline: FastMemoryCommitPipeline,
        min_batch_size: int = 1,
        max_batch_size: int = 50,
    ) -> DistillationReport | None:
        """Poll the pipeline for pending records and execute an idle distillation cycle.

        Args:
            pipeline: The fast memory commit pipeline holding un-distilled records.
            min_batch_size: Minimum number of pending records required to trigger distillation.
            max_batch_size: Maximum batch capacity per idle cycle.

        Returns:
            DistillationReport if distillation occurred, or None if idle threshold not met.
        """
        pending = pipeline.get_pending_records(limit=max_batch_size)
        if len(pending) < min_batch_size:
            return None

        batch = DistillationBatch(
            batch_id=f"distill-{uuid.uuid4().hex[:12]}",
            records=pending,
            created_at=datetime.now(UTC),
        )

        report = self.distill_batch(batch)

        # Notify pipeline to transition distilled records and prune cache
        processed_ids = [r.record_id for r in pending]
        pipeline.mark_distilled(processed_ids)
        pipeline.prune_distilled()

        return report

    def _consolidate_facts(self, raw_facts: Sequence[str]) -> list[str]:
        """Cluster and deduplicate facts into canonical synthesized propositions."""
        if not raw_facts:
            return []

        consolidated: list[str] = []
        seen_normalized: set[str] = set()

        for f in raw_facts:
            norm = self._normalize_proposition(f)
            if not norm or norm in seen_normalized:
                continue

            # Check fuzzy containment against existing consolidated facts
            is_redundant = False
            for existing in consolidated:
                if self._is_subsumed(norm, existing.lower()):
                    is_redundant = True
                    break

            if not is_redundant:
                seen_normalized.add(norm)
                # Capitalize first letter cleanly
                consolidated.append(f.strip()[:1].upper() + f.strip()[1:])

        return consolidated

    def _normalize_proposition(self, text: str) -> str:
        """Normalize punctuation and whitespace for canonical matching."""
        cleaned = "".join(ch.lower() for ch in text if ch.isalnum() or ch.isspace())
        return " ".join(cleaned.split())

    def _is_subsumed(self, candidate_norm: str, existing_norm: str) -> bool:
        """Return True if candidate is logically subsumed by or near-duplicate of existing."""
        if candidate_norm in existing_norm or existing_norm in candidate_norm:
            return True

        tokens_cand = set(candidate_norm.split())
        tokens_exist = set(existing_norm.split())

        if not tokens_cand or not tokens_exist:
            return False

        intersection = len(tokens_cand.intersection(tokens_exist))
        jaccard = intersection / float(len(tokens_cand.union(tokens_exist)))
        return jaccard >= self._similarity_threshold
