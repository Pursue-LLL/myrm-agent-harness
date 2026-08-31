"""Data types and event contracts for the dual-lane ingest pipeline.

Defines the payload types, task envelopes, and lifecycle sentinels that flow
through the Object Lane, Job Lane, bounded chunk queue, and batch embed consumer.

[INPUT]
- None (pure domain contracts)

[OUTPUT]
- Chunk: Atomic text slice with content and metadata
- EndOfTask: Sentinel indicating an object task has finished processing
- TaskEnvelope: Strongly-typed queue item pairing payload with task identity
- DirNode: Directory tree DAG node for Job Lane bottom-up reduce
- IngestStats: Summary statistics of an ingestion run
- IngestEvent: Event emitted during ingestion progress

[POS]
Data contract layer for toolkits.retriever.ingest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Literal


class TaskStatus(Enum):
    """Lifecycle status of an individual object task."""

    PENDING = auto()
    PROCESSING = auto()
    SUCCESS = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass(slots=True)
class Chunk:
    """Atomic text chunk with origin and metadata."""

    content: str
    uri: str
    chunk_index: int = 0
    total_chunks: int = 1
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)
    is_summary: bool = False


@dataclass(slots=True)
class EndOfTask:
    """Sentinel indicating an object's chunk stream has ended."""

    uri: str
    status: TaskStatus = TaskStatus.SUCCESS
    error_message: str | None = None
    chunks_produced: int = 0


@dataclass(slots=True)
class TaskEnvelope:
    """Strongly-typed queue item carrying task identity and payload."""

    task_id: str
    payload: Chunk | EndOfTask


@dataclass(slots=True)
class DirNode:
    """Node in the directory tree DAG used by Job Lane for bottom-up summarization."""

    path: str
    parent_path: str | None
    depth: int
    children_files: list[str] = field(default_factory=list)
    children_dirs: list[str] = field(default_factory=list)
    pending_children_count: int = 0
    is_summarized: bool = False
    summary_text: str | None = None


@dataclass(slots=True)
class IngestStats:
    """Aggregate execution statistics for an ingest run."""

    total_objects: int = 0
    succeeded_objects: int = 0
    failed_objects: int = 0
    skipped_objects: int = 0
    total_chunks_produced: int = 0
    total_chunks_embedded: int = 0
    total_directories_summarized: int = 0
    duration_seconds: float = 0.0


@dataclass(slots=True)
class IngestEvent:
    """Progress event emitted during pipeline execution."""

    event_type: Literal[
        "object_start",
        "object_success",
        "object_failed",
        "dir_summarized",
        "embed_batch_flushed",
        "pipeline_completed",
    ]
    uri: str | None = None
    message: str = ""
    stats: IngestStats | None = None
