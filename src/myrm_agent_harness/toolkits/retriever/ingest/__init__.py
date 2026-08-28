"""Dual-Lane Ingest Pipeline package.

Provides high-throughput, bounded-backpressure data and knowledge ingestion
with decoupled Object Lane (micro chunks) and Job Lane (macro directory tree summarization).
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.retriever.ingest.consumer import BatchEmbedConsumer
from myrm_agent_harness.toolkits.retriever.ingest.pipeline import (
    DirSummarizerFunc,
    DualLaneIngestPipeline,
    ObjectProducerFunc,
)
from myrm_agent_harness.toolkits.retriever.ingest.tree import (
    DirTreeBuilder,
    ancestor_dirs,
    dir_depth,
)
from myrm_agent_harness.toolkits.retriever.ingest.types import (
    Chunk,
    DirNode,
    EndOfTask,
    IngestEvent,
    IngestStats,
    TaskEnvelope,
    TaskStatus,
)

__all__ = [
    "BatchEmbedConsumer",
    "Chunk",
    "DirNode",
    "DirSummarizerFunc",
    "DirTreeBuilder",
    "DualLaneIngestPipeline",
    "EndOfTask",
    "IngestEvent",
    "IngestStats",
    "ObjectProducerFunc",
    "TaskEnvelope",
    "TaskStatus",
    "ancestor_dirs",
    "dir_depth",
]
