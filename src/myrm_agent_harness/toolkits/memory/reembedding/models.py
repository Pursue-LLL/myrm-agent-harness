"""Data models for ZeroDowntimeCrossDimensionReembeddingEngine.

Defines job configurations, progress trackers, dual-version collection states,
and adaptive batch payloads with strict type safety.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ReembeddingStatus: Execution status for cross-dimension re-embedding jobs.
- ReembeddingJobConfig: Configuration for cross-dimension re-embedding migration.
- ReembeddingRecord: Single raw memory text payload to be re-embedded.
- ReembeddingBatch: Adaptive batch slice tailored to character budget.
- DualVersionCollectionState: State descriptor for zero-downtime blue-green dual-version collections.
- ReembeddingProgress: Real-time observability snapshot for re-embedding progression.

[POS]
Data models for ZeroDowntimeCrossDimensionReembeddingEngine.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ReembeddingStatus(StrEnum):
    """Execution status for cross-dimension re-embedding jobs."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class ReembeddingJobConfig:
    """Configuration for cross-dimension re-embedding migration."""

    job_id: str
    source_dimension: int
    target_dimension: int
    target_model_name: str
    min_batch_size: int = 10
    max_batch_size: int = 32
    max_chars_per_batch: int = 4000


@dataclass(frozen=True)
class ReembeddingRecord:
    """Single raw memory text payload to be re-embedded."""

    record_id: str
    content: str
    metadata: Mapping[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class ReembeddingBatch:
    """Adaptive batch slice tailored to character budget."""

    batch_id: int
    records: list[ReembeddingRecord]
    total_characters: int


@dataclass(frozen=True)
class DualVersionCollectionState:
    """State descriptor for zero-downtime blue-green dual-version collections."""

    source_collection: str
    staging_collection: str
    active_collection: str
    is_cutover_ready: bool = False
    cutover_completed: bool = False


@dataclass(frozen=True)
class ReembeddingProgress:
    """Real-time observability snapshot for re-embedding progression."""

    job_id: str
    status: ReembeddingStatus
    total_records: int
    processed_records: int
    failed_records: int
    current_cursor: str | None
    throughput_per_sec: float
    estimated_remaining_seconds: float
    started_at: str
    updated_at: str

    @classmethod
    def initial(cls, job_id: str, total_records: int) -> "ReembeddingProgress":
        """Instantiate initial progress record."""
        now_iso = datetime.now(UTC).isoformat()
        return cls(
            job_id=job_id,
            status=ReembeddingStatus.IDLE,
            total_records=total_records,
            processed_records=0,
            failed_records=0,
            current_cursor=None,
            throughput_per_sec=0.0,
            estimated_remaining_seconds=0.0,
            started_at=now_iso,
            updated_at=now_iso,
        )
