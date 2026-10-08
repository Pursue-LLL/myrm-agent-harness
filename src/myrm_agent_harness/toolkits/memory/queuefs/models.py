"""[POS]: src/myrm_agent_harness/toolkits/memory/queuefs/models.py
[INPUT]: Resource URIs, DAG processing stages, and concurrent lock lease parameters.
[OUTPUT]: Strongly typed domain models for QueueFS asynchronous semantic DAG processing and path locks.
"""

import time
from enum import StrEnum

from pydantic import BaseModel, Field


class SemanticTaskStatus(StrEnum):
    """Execution status of an asynchronous semantic processing task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SemanticDAGStage(StrEnum):
    """Discrete sequential stages in the QueueFS semantic processing DAG."""

    INGESTION = "ingestion"
    CHUNKING = "chunking"
    SIDECAR = "sidecar"
    EMBEDDING = "embedding"
    INDEXING = "indexing"


class SemanticLockMode(StrEnum):
    """Concurrency lock mode governing resource paths."""

    EXCLUSIVE = "exclusive"
    SHARED = "shared"


class SemanticLockLease(BaseModel):
    """Lease token representing an active lock over a virtual path pattern."""

    lock_id: str = Field(..., description="Unique lease identifier")
    path_pattern: str = Field(..., description="Locked canonical path or directory prefix")
    mode: SemanticLockMode = Field(..., description="Acquired lock mode (exclusive/shared)")
    owner: str = Field(..., description="Owner session, agent, or worker ID")
    acquired_at_epoch: float = Field(..., description="Acquisition epoch timestamp in seconds")
    expires_at_epoch: float = Field(..., description="Expiration epoch timestamp in seconds")

    def is_expired(self, now_epoch: float | None = None) -> bool:
        """Check if lease has elapsed past its expiration threshold."""
        current = time.time() if now_epoch is None else now_epoch
        return current >= self.expires_at_epoch


class SemanticDAGTask(BaseModel):
    """Asynchronous semantic processing task executing across DAG stages."""

    task_id: str = Field(..., description="Unique task identifier")
    resource_uri: str = Field(..., description="Canonical URI of the resource being indexed")
    payload: str = Field(default="", description="Optional raw text payload or preview")
    stages: list[SemanticDAGStage] = Field(
        default_factory=lambda: [
            SemanticDAGStage.INGESTION,
            SemanticDAGStage.CHUNKING,
            SemanticDAGStage.SIDECAR,
            SemanticDAGStage.EMBEDDING,
            SemanticDAGStage.INDEXING,
        ],
        description="Planned DAG stages for this resource",
    )
    current_stage: SemanticDAGStage = Field(
        default=SemanticDAGStage.INGESTION,
        description="Currently active or last executed DAG stage",
    )
    status: SemanticTaskStatus = Field(
        default=SemanticTaskStatus.PENDING,
        description="Current overall task execution state",
    )
    progress_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Completion progress percentage (0.0 to 100.0)",
    )
    created_at_epoch: float = Field(default_factory=time.time, description="Creation epoch timestamp")
    updated_at_epoch: float = Field(default_factory=time.time, description="Last updated epoch timestamp")
    error_message: str | None = Field(default=None, description="Diagnostic error message on failure")


class QueueFSConfig(BaseModel):
    """Configuration governing QueueFS worker concurrency and lock lifetimes."""

    max_concurrent_workers: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Maximum concurrent worker tasks executed simultaneously",
    )
    lock_ttl_seconds: float = Field(
        default=30.0,
        gt=0.0,
        le=300.0,
        description="Default lease time-to-live in seconds before auto-expiration",
    )
    auto_cleanup_completed_after_seconds: float = Field(
        default=3600.0,
        ge=60.0,
        description="Time before finished tasks are purged from active tracking",
    )


class QueueFSStats(BaseModel):
    """Telemetry metrics reflecting QueueFS queue depths and active locks."""

    pending_tasks: int = Field(default=0, ge=0, description="Tasks awaiting execution")
    running_tasks: int = Field(default=0, ge=0, description="Tasks actively being processed")
    completed_tasks: int = Field(default=0, ge=0, description="Successfully finished tasks")
    failed_tasks: int = Field(default=0, ge=0, description="Tasks halted due to errors")
    active_locks: int = Field(default=0, ge=0, description="Currently held path lock leases")
