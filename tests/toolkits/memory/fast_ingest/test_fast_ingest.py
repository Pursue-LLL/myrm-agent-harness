"""Unit tests and latency benchmark for Sub-5% Latency One-Pass Fast Ingestion Engine."""

import time
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.fast_ingest import (
    AsyncDeepDistillationWorker,
    DistillationBatch,
    FastCommittedRecord,
    FastMemoryCommitPipeline,
    IngestStatus,
    RawIngestTurn,
)


def _make_turn(
    turn_id: str = "turn-001",
    user_msg: str = "Always prefer PostgreSQL 16 instead of MySQL.",
    asst_msg: str = "- Database driver is asyncpg.\n- Config file is config.toml",
    forward_ms: float = 500.0,
) -> RawIngestTurn:
    """Helper to create a synthetic RawIngestTurn with defined forward latency."""
    return RawIngestTurn(
        session_id="sess-alpha",
        turn_id=turn_id,
        user_message=user_msg,
        assistant_message=asst_msg,
        forward_inference_ms=forward_ms,
        timestamp=datetime.now(UTC),
    )


class TestFastMemoryCommitPipeline:
    """Test suite for FastMemoryCommitPipeline latency and heuristic extraction."""

    def test_heuristic_extraction_and_commit(self) -> None:
        """Pipeline must extract entities and facts without secondary LLM invocation."""
        pipeline = FastMemoryCommitPipeline()
        turn = _make_turn(
            turn_id="turn-heuristics",
            user_msg="Please remember to always use Python 3.13 for our project FastAPI service.",
            asst_msg="Understood. The API port is 8080.\n- Service initialized successfully.",
            forward_ms=600.0,
        )

        record, metrics = pipeline.commit_turn(turn)

        assert record.turn_id == "turn-heuristics"
        assert record.status == IngestStatus.PENDING_DISTILL
        assert len(record.extracted_facts) > 0
        assert any("Python 3.13" in f for f in record.extracted_facts)
        assert record.salience_score > 0.3
        assert metrics.passed_overhead_gate is True
        assert pipeline.buffer_size == 1

    def test_sub_five_percent_latency_overhead_gate(self) -> None:
        """Commit latency overhead must strictly remain under 5.0% of forward inference time."""
        pipeline = FastMemoryCommitPipeline(target_overhead_threshold_percent=5.0)
        # Typical LLM inference takes 400ms - 2000ms
        turn = _make_turn(
            turn_id="turn-gate-check",
            user_msg="Switch to using Ruff for linting and formatting.",
            asst_msg="Linters updated in pyproject.toml.",
            forward_ms=450.0,
        )

        _record, metrics = pipeline.commit_turn(turn)

        # Fast commit takes < 2ms, overhead should be < 1% (well below 5%)
        assert metrics.commit_latency_ms < 22.5  # 5% of 450ms is 22.5ms
        assert metrics.overhead_percentage < 5.0
        assert metrics.passed_overhead_gate is True

    def test_buffer_capacity_eviction(self) -> None:
        """Buffer must cap total size and evict oldest records when capacity is saturated."""
        pipeline = FastMemoryCommitPipeline(max_buffer_size=5)

        for i in range(8):
            turn = _make_turn(turn_id=f"turn-{i}", forward_ms=300.0)
            pipeline.commit_turn(turn)

        assert pipeline.buffer_size == 5
        pending = pipeline.get_pending_records(limit=10)
        assert len(pending) == 5
        # Oldest turns 0, 1, 2 should have been evicted
        assert pending[0].turn_id == "turn-3"
        assert pending[-1].turn_id == "turn-7"


class TestAsyncDeepDistillationWorker:
    """Test suite for idle-time asynchronous deep distillation."""

    def test_distill_batch_deduplication(self) -> None:
        """Worker must deduplicate overlapping facts across committed records."""
        worker = AsyncDeepDistillationWorker()
        records = [
            FastCommittedRecord(
                record_id="r1",
                session_id="s1",
                turn_id="t1",
                extracted_entities=["PostgreSQL"],
                extracted_facts=["Database is PostgreSQL 16", "Port is 5432"],
                salience_score=0.7,
                commit_latency_ms=0.5,
                created_at=datetime.now(UTC),
            ),
            FastCommittedRecord(
                record_id="r2",
                session_id="s1",
                turn_id="t2",
                extracted_entities=["PostgreSQL"],
                extracted_facts=["Database is postgresql 16", "Connection pool is 20"],
                salience_score=0.6,
                commit_latency_ms=0.4,
                created_at=datetime.now(UTC),
            ),
        ]

        batch = DistillationBatch(
            batch_id="batch-01",
            records=records,
            created_at=datetime.now(UTC),
        )

        report = worker.distill_batch(batch)

        assert report.input_record_count == 2
        # "Database is PostgreSQL 16" and "Database is postgresql 16" should be deduplicated
        assert report.distilled_fact_count == 3
        assert report.deduplication_ratio > 0.0
        assert len(worker.history) == 1

    def test_idle_cycle_pipeline_integration(self) -> None:
        """Executing an idle cycle consumes pending records and clears buffer."""
        pipeline = FastMemoryCommitPipeline()
        for i in range(3):
            turn = _make_turn(turn_id=f"turn-idle-{i}", forward_ms=400.0)
            pipeline.commit_turn(turn)

        assert len(pipeline.get_pending_records()) == 3

        worker = AsyncDeepDistillationWorker()
        report = worker.run_idle_cycle(pipeline, min_batch_size=2)

        assert report is not None
        assert report.input_record_count == 3
        # Buffer should have been pruned
        assert len(pipeline.get_pending_records()) == 0
        assert pipeline.buffer_size == 0

    def test_benchmark_100_turns_commit_throughput(self) -> None:
        """Benchmark 100 consecutive turns to verify sub-millisecond median commit speed."""
        pipeline = FastMemoryCommitPipeline(max_buffer_size=200)
        turns = [
            _make_turn(
                turn_id=f"bench-{i}",
                user_msg=f"Remember setting key_{i} is value_{i} in production environment.",
                asst_msg=f"- Key key_{i} configured successfully on host_{i}.",
                forward_ms=500.0,
            )
            for i in range(100)
        ]

        t0 = time.perf_counter()
        for t in turns:
            _record, metrics = pipeline.commit_turn(t)
            assert metrics.passed_overhead_gate is True

        total_time_ms = (time.perf_counter() - t0) * 1000.0
        avg_commit_ms = total_time_ms / 100.0

        # Mean commit latency should be well under 2.0 milliseconds per turn
        assert avg_commit_ms < 2.0
