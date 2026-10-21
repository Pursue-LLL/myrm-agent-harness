"""Strongly typed data contracts for GUI task chunking pipeline and row-level checkpoints.

Benchmarked against OpenAI Codex Computer Use Principle 2 (Chunked Pipelines & Intermediate Files):
- Dissects long 50-100 step operation chains into atomic 3-5 step manageable stages.
- Enforces row-level progress checkpoint manifests with atomic persistence to prevent corruption.
- Guarantees skip-ahead resumption upon failure, preventing token waste and duplicate submissions.

[OUTPUT]
- RowProcessingStatus: Processing lifecycle status of an individual row (PENDING, SUCCESS, FAILED, SKIPPED).
- PipelineStageKind: Canonical stage categorization in chunked automation workflows.
- RowCheckpointItem: Detailed record of an individual row's inputs, outputs, and proof artifacts.
- BatchPipelineProgress: Overall execution metrics and completion summary across all rows.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- RowProcessingStatus
- PipelineStageKind
- RowCheckpointItem
- BatchPipelineProgress

[POS]
Strongly typed data contracts for GUI task chunking pipeline and row-level checkpoints.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class RowProcessingStatus(StrEnum):
    """Lifecycle state of an individual row item within a batch pipeline."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStageKind(StrEnum):
    """High-level stage classification in chunked operation workflows."""

    DISCOVERY = "discovery"
    """Scanning target inputs, extracting ID list, creating initial manifest."""

    BATCH_EXECUTION = "batch_execution"
    """Iterating through row items in atomic chunks (3-5 steps per row)."""

    CONSOLIDATION = "consolidation"
    """Aggregating successfully processed row records into the final deliverable."""


@dataclass(frozen=True)
class RowCheckpointItem:
    """Atomic checkpoint record for a single processed row in the pipeline."""

    row_id: str
    payload: dict[str, str]
    status: RowProcessingStatus
    proof_artifact_path: str = ""
    error_message: str = ""
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class BatchPipelineProgress:
    """Consolidated execution progress across the entire chunked batch pipeline."""

    pipeline_id: str
    stage: PipelineStageKind
    total_rows: int
    completed_rows: int
    failed_rows: int
    skipped_rows: int
    is_finished: bool
    manifest_path: str
    timestamp: float = field(default_factory=time.time)

    @property
    def remaining_rows(self) -> int:
        """Count of rows still awaiting successful processing."""
        return max(0, self.total_rows - self.completed_rows - self.skipped_rows)
