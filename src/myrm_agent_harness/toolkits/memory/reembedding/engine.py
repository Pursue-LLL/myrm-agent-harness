"""Zero-downtime cross-dimension re-embedding orchestrator engine.

Coordinates blue-green collection transitions, adaptive batching execution,
breakpoint cursor persistence, and atomic hot-cutover routing.
"""

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from .batcher import AdaptiveBatcher
from .checkpoint import ReembeddingCheckpointManager
from .models import (
    DualVersionCollectionState,
    ReembeddingJobConfig,
    ReembeddingProgress,
    ReembeddingRecord,
    ReembeddingStatus,
)

EmbeddingFunction = Callable[[Sequence[str]], Sequence[list[float]]]
VectorBatchWriter = Callable[[str, Sequence[str], Sequence[list[float]]], None]


class ZeroDowntimeReembeddingEngine:
    """Orchestrates zero-downtime re-embedding with adaptive batching and breakpoint recovery."""

    def __init__(
        self,
        checkpoint_manager: ReembeddingCheckpointManager | None = None,
    ) -> None:
        """Initialize engine with optional custom checkpoint persistence."""
        self._checkpoints = checkpoint_manager or ReembeddingCheckpointManager()
        self._collection_states: dict[str, DualVersionCollectionState] = {}
        self._progress_snapshots: dict[str, ReembeddingProgress] = {}

    def init_collection_state(
        self,
        source_collection: str,
        staging_collection: str,
    ) -> DualVersionCollectionState:
        """Initialize blue-green collection state with read traffic bound to source."""
        state = DualVersionCollectionState(
            source_collection=source_collection,
            staging_collection=staging_collection,
            active_collection=source_collection,
            is_cutover_ready=False,
            cutover_completed=False,
        )
        self._collection_states[source_collection] = state
        return state

    def route_query_collection(self, source_collection: str) -> str:
        """Route read traffic to active collection ensuring 100% availability."""
        state = self._collection_states.get(source_collection)
        if state is None:
            return source_collection
        return state.active_collection

    def get_progress(self, job_id: str) -> ReembeddingProgress | None:
        """Retrieve real-time re-embedding progress snapshot."""
        return self._progress_snapshots.get(job_id)

    def execute_migration(
        self,
        config: ReembeddingJobConfig,
        records: Sequence[ReembeddingRecord],
        embed_fn: EmbeddingFunction,
        write_fn: VectorBatchWriter,
        source_collection: str,
        staging_collection: str,
    ) -> ReembeddingProgress:
        """Execute or resume adaptive re-embedding into the staging collection."""
        state = self.init_collection_state(source_collection, staging_collection)

        # 1. Checkpoint filter: discard already completed records
        completed_ids = self._checkpoints.filter_unprocessed(
            config.job_id,
            [r.record_id for r in records],
        )
        unprocessed_lookup = set(completed_ids)
        pending_records = [r for r in records if r.record_id in unprocessed_lookup]

        total_count = len(records)
        processed_count = total_count - len(pending_records)
        start_time = time.monotonic()

        progress = ReembeddingProgress(
            job_id=config.job_id,
            status=ReembeddingStatus.RUNNING,
            total_records=total_count,
            processed_records=processed_count,
            failed_records=0,
            current_cursor=None,
            throughput_per_sec=0.0,
            estimated_remaining_seconds=0.0,
            started_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
        self._progress_snapshots[config.job_id] = progress

        if not pending_records:
            # Everything already processed from prior checkpoint
            self._collection_states[source_collection] = DualVersionCollectionState(
                source_collection=state.source_collection,
                staging_collection=state.staging_collection,
                active_collection=state.active_collection,
                is_cutover_ready=True,
                cutover_completed=state.cutover_completed,
            )
            return self._finalize_progress(progress, processed_count, 0, start_time)

        # 2. Adaptive slicing
        batches = AdaptiveBatcher.slice_into_batches(pending_records, config)

        for batch in batches:
            batch_texts = [r.content for r in batch.records]
            batch_ids = [r.record_id for r in batch.records]

            try:
                # Compute target embeddings and write to staging
                vectors = embed_fn(batch_texts)
                write_fn(staging_collection, batch_ids, vectors)

                # Persist breakpoint
                processed_count += len(batch.records)
                cursor = batch_ids[-1]
                self._checkpoints.record_progress(
                    job_id=config.job_id,
                    cursor=cursor,
                    processed_batch_ids=batch_ids,
                )

                elapsed = max(0.001, time.monotonic() - start_time)
                throughput = round(processed_count / elapsed, 2)
                remaining_items = total_count - processed_count
                eta = round(remaining_items / max(throughput, 0.01), 2)

                progress = ReembeddingProgress(
                    job_id=config.job_id,
                    status=ReembeddingStatus.RUNNING,
                    total_records=total_count,
                    processed_records=processed_count,
                    failed_records=progress.failed_records,
                    current_cursor=cursor,
                    throughput_per_sec=throughput,
                    estimated_remaining_seconds=eta,
                    started_at=progress.started_at,
                    updated_at=datetime.now(UTC).isoformat(),
                )
                self._progress_snapshots[config.job_id] = progress

            except Exception:
                progress = ReembeddingProgress(
                    job_id=config.job_id,
                    status=ReembeddingStatus.FAILED,
                    total_records=total_count,
                    processed_records=processed_count,
                    failed_records=progress.failed_records + len(batch.records),
                    current_cursor=progress.current_cursor,
                    throughput_per_sec=progress.throughput_per_sec,
                    estimated_remaining_seconds=progress.estimated_remaining_seconds,
                    started_at=progress.started_at,
                    updated_at=datetime.now(UTC).isoformat(),
                )
                self._progress_snapshots[config.job_id] = progress
                raise

        # Mark staging ready for cutover
        self._checkpoints.mark_completed(config.job_id)
        self._collection_states[source_collection] = DualVersionCollectionState(
            source_collection=state.source_collection,
            staging_collection=state.staging_collection,
            active_collection=state.active_collection,
            is_cutover_ready=True,
            cutover_completed=state.cutover_completed,
        )

        return self._finalize_progress(progress, processed_count, 0, start_time)

    def perform_hot_cutover(self, source_collection: str) -> DualVersionCollectionState:
        """Atomically redirect read traffic to the staging collection."""
        state = self._collection_states.get(source_collection)
        if state is None:
            raise KeyError(f"No collection state registered for {source_collection}")

        if not state.is_cutover_ready:
            raise RuntimeError(
                f"Collection {source_collection} is not ready for cutover; migration must complete first."
            )

        new_state = DualVersionCollectionState(
            source_collection=state.source_collection,
            staging_collection=state.staging_collection,
            active_collection=state.staging_collection,
            is_cutover_ready=True,
            cutover_completed=True,
        )
        self._collection_states[source_collection] = new_state
        return new_state

    @staticmethod
    def _finalize_progress(
        progress: ReembeddingProgress,
        processed: int,
        failed: int,
        start_time: float,
    ) -> ReembeddingProgress:
        """Generate final completed progress snapshot."""
        elapsed = max(0.001, time.monotonic() - start_time)
        throughput = round(processed / elapsed, 2)
        return ReembeddingProgress(
            job_id=progress.job_id,
            status=ReembeddingStatus.COMPLETED,
            total_records=progress.total_records,
            processed_records=processed,
            failed_records=failed,
            current_cursor=progress.current_cursor,
            throughput_per_sec=throughput,
            estimated_remaining_seconds=0.0,
            started_at=progress.started_at,
            updated_at=datetime.now(UTC).isoformat(),
        )
