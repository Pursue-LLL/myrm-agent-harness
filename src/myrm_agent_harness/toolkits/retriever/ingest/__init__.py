"""Dual-Lane Ingest Pipeline package.

[INPUT]
- .consumer::BatchEmbedConsumer (POS: bounded queue drainer with batch embedding)
- .pipeline::DualLaneIngestPipeline (POS: main coordinator for dual-lane ingestion)
- .tree::DirTreeBuilder (POS: in-memory directory DAG builder)
- .types::Chunk, DirNode, EndOfTask, IngestEvent, IngestStats, TaskEnvelope, TaskStatus (POS: data contracts)

[OUTPUT]
- BatchEmbedConsumer, DualLaneIngestPipeline, DirTreeBuilder, Chunk, IngestEvent, TaskEnvelope

[POS]
Retriever Ingest 双车道管道模块入口。解耦原子微切片与宏观目录树拓扑聚合，提供常量内存级大规模入库。
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
