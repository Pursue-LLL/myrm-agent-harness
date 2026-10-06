"""Unit tests for ZeroDowntimeCrossDimensionReembeddingEngine and Breakpoint Resume."""

import pytest

from myrm_agent_harness.toolkits.memory.reembedding import (
    AdaptiveBatcher,
    ReembeddingCheckpointManager,
    ReembeddingJobConfig,
    ReembeddingRecord,
    ReembeddingStatus,
    ZeroDowntimeReembeddingEngine,
)


def test_adaptive_batcher_dynamic_character_partitioning() -> None:
    """Test adaptive batching respects character budgets and min/max limits."""
    config = ReembeddingJobConfig(
        job_id="job_test_batch",
        source_dimension=384,
        target_dimension=1024,
        target_model_name="qwen3-embedding",
        min_batch_size=2,
        max_batch_size=5,
        max_chars_per_batch=50,
    )

    # 1. Ten short records (each 10 chars -> 100 chars total)
    short_records = [
        ReembeddingRecord(record_id=f"rec_short_{i}", content="0123456789")
        for i in range(10)
    ]
    batches = AdaptiveBatcher.slice_into_batches(short_records, config)
    assert len(batches) == 2
    assert len(batches[0].records) == 5
    assert len(batches[1].records) == 5
    assert batches[0].total_characters == 50

    # 2. Oversized single record (> 50 chars) should be isolated
    long_record = ReembeddingRecord(
        record_id="rec_long",
        content="X" * 120,
    )
    mixed_records = [short_records[0], long_record, short_records[1]]
    mixed_batches = AdaptiveBatcher.slice_into_batches(mixed_records, config)
    assert len(mixed_batches) == 3
    assert mixed_batches[1].records[0].record_id == "rec_long"
    assert mixed_batches[1].total_characters == 120

    # 3. Empty input edge case
    assert AdaptiveBatcher.slice_into_batches([], config) == []


def test_checkpoint_manager_and_breakpoint_resumption() -> None:
    """Test persistent checkpoint tracking and idempotent record filtering."""
    manager = ReembeddingCheckpointManager()
    job_id = "job_checkpoint_001"

    assert manager.get_checkpoint(job_id) is None

    # Step 1: Process first batch of 3 records
    manager.record_progress(
        job_id=job_id,
        cursor="rec_3",
        processed_batch_ids=["rec_1", "rec_2", "rec_3"],
    )

    state = manager.get_checkpoint(job_id)
    assert state is not None
    assert state.last_cursor == "rec_3"
    assert state.processed_record_ids == {"rec_1", "rec_2", "rec_3"}
    assert state.is_completed is False

    # Step 2: Filter unprocessed IDs
    all_candidate_ids = ["rec_1", "rec_2", "rec_3", "rec_4", "rec_5"]
    unprocessed = manager.filter_unprocessed(job_id, all_candidate_ids)
    assert unprocessed == ["rec_4", "rec_5"]

    # Step 3: Complete remaining records
    manager.record_progress(
        job_id=job_id,
        cursor="rec_5",
        processed_batch_ids=["rec_4", "rec_5"],
    )
    manager.mark_completed(job_id)
    final_state = manager.get_checkpoint(job_id)
    assert final_state is not None
    assert final_state.is_completed is True
    assert len(manager.filter_unprocessed(job_id, all_candidate_ids)) == 0


def test_zero_downtime_engine_migration_and_atomic_cutover() -> None:
    """Test full migration lifecycle, zero-downtime routing, and atomic cutover."""
    checkpoint_mgr = ReembeddingCheckpointManager()
    engine = ZeroDowntimeReembeddingEngine(checkpoint_manager=checkpoint_mgr)

    config = ReembeddingJobConfig(
        job_id="job_live_001",
        source_dimension=384,
        target_dimension=1024,
        target_model_name="qwen3-embedding",
        min_batch_size=2,
        max_batch_size=3,
        max_chars_per_batch=100,
    )

    records = [
        ReembeddingRecord(record_id=f"doc_{i}", content=f"Memory content sample {i}")
        for i in range(6)
    ]

    source_col = "mem_source_384d"
    staging_col = "mem_staging_1024d"

    # Verify query routing before migration: points to source
    engine.init_collection_state(source_col, staging_col)
    assert engine.route_query_collection(source_col) == source_col

    # Mock embedding generator and vector batch writer
    written_batches: list[tuple[str, list[str], list[list[float]]]] = []

    def mock_embed(texts: list[str]) -> list[list[float]]:
        # return dummy 1024-dimension vectors
        return [[0.1] * 1024 for _ in texts]

    def mock_write(collection: str, ids: list[str], vectors: list[list[float]]) -> None:
        written_batches.append((collection, list(ids), list(vectors)))

    # Execute migration
    progress = engine.execute_migration(
        config=config,
        records=records,
        embed_fn=mock_embed,
        write_fn=mock_write,
        source_collection=source_col,
        staging_collection=staging_col,
    )

    assert progress.status == ReembeddingStatus.COMPLETED
    assert progress.total_records == 6
    assert progress.processed_records == 6
    assert progress.failed_records == 0

    # Ensure writes occurred strictly into staging collection
    assert len(written_batches) > 0
    assert all(col == staging_col for col, _, _ in written_batches)

    # Before cutover: read queries must STILL route to source collection (Zero Downtime)
    assert engine.route_query_collection(source_col) == source_col

    # Perform atomic hot cutover
    cutover_state = engine.perform_hot_cutover(source_col)
    assert cutover_state.cutover_completed is True
    assert cutover_state.active_collection == staging_col

    # After cutover: read queries seamlessly route to staging collection
    assert engine.route_query_collection(source_col) == staging_col


def test_zero_downtime_engine_breakpoint_resume_midway() -> None:
    """Test engine seamlessly resumes from an interrupted execution."""
    checkpoint_mgr = ReembeddingCheckpointManager()
    engine = ZeroDowntimeReembeddingEngine(checkpoint_manager=checkpoint_mgr)

    config = ReembeddingJobConfig(
        job_id="job_resume_002",
        source_dimension=384,
        target_dimension=1024,
        target_model_name="qwen3-embedding",
        min_batch_size=2,
        max_batch_size=2,
        max_chars_per_batch=100,
    )

    records = [
        ReembeddingRecord(record_id=f"item_{i}", content=f"Text item {i}")
        for i in range(4)
    ]

    source_col = "legacy_mem_384"
    staging_col = "new_mem_1024"

    # Simulate prior crash after processing first 2 records
    checkpoint_mgr.record_progress(
        job_id=config.job_id,
        cursor="item_1",
        processed_batch_ids=["item_0", "item_1"],
    )

    written_ids: list[str] = []

    def mock_embed(texts: list[str]) -> list[list[float]]:
        return [[0.2] * 1024 for _ in texts]

    def mock_write(collection: str, ids: list[str], vectors: list[list[float]]) -> None:
        written_ids.extend(ids)

    # Resume migration
    progress = engine.execute_migration(
        config=config,
        records=records,
        embed_fn=mock_embed,
        write_fn=mock_write,
        source_collection=source_col,
        staging_collection=staging_col,
    )

    assert progress.status == ReembeddingStatus.COMPLETED
    assert progress.total_records == 4
    assert progress.processed_records == 4
    # Only items 2 and 3 should have been written in this resumed invocation
    assert written_ids == ["item_2", "item_3"]

    # Cutover can now proceed
    cutover = engine.perform_hot_cutover(source_col)
    assert cutover.active_collection == staging_col


def test_cutover_fails_if_not_ready() -> None:
    """Ensure hot cutover raises error if migration has not completed."""
    engine = ZeroDowntimeReembeddingEngine()
    engine.init_collection_state("src_col", "staging_col")

    with pytest.raises(RuntimeError, match="not ready for cutover"):
        engine.perform_hot_cutover("src_col")

    with pytest.raises(KeyError, match="No collection state"):
        engine.perform_hot_cutover("non_existent_col")
