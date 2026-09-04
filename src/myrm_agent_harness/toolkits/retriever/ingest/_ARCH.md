# ingest/

## Overview
Dual-Lane Ingest Pipeline with bounded backpressure. Decouples Object Lane (micro atomic chunking)
from Job Lane (macro directory tree DAG summarization), feeding a bounded in-memory chunk queue
drained by a process-level BatchEmbedConsumer to guarantee constant O(1) memory usage during massive ingestion.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for dual-lane ingestion | ✅ |
| `types.py` | Core | Data contracts: Chunk, TaskEnvelope, EndOfTask, DirNode, IngestStats, IngestEvent | ✅ |
| `tree.py` | Core | DirTreeBuilder: In-memory directory DAG with bottom-up topological reduce | ✅ |
| `consumer.py` | Core | BatchEmbedConsumer: Bounded queue drainer with batch embedding and idle flush | ✅ |
| `pipeline.py` | Core | DualLaneIngestPipeline: Main coordinator orchestrating Object & Job lanes with backpressure | ✅ |

## Architecture Principles
1. **O(1) Bounded Memory**: `asyncio.Queue(maxsize=batch_size * 2)` puts backpressure on producers, preventing OOM spikes.
2. **Dual-Lane Decoupling**: Job Lane directory summarization only needs text summaries from child directories; it does not wait for Object Lane embedding computations.
3. **Task-Level Fault Isolation**: Failures in single object chunking emit `TaskStatus.FAILED` sentinels without aborting the batch.
