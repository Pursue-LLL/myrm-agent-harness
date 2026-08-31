"""Dual-Lane Ingest Pipeline with Bounded Queue Backpressure.

Orchestrates the Object Lane (micro atomic chunking), Job Lane (macro directory tree
bottom-up summarization), and unified BatchEmbedConsumer over a strictly bounded
asyncio.Queue to eliminate memory spikes and OOM crashes during massive ingestion.

[INPUT]
- types.py::Chunk, EndOfTask, TaskEnvelope, IngestStats, IngestEvent, TaskStatus
- tree.py::DirTreeBuilder
- consumer.py::BatchEmbedConsumer
- toolkits.memory.protocols.embedding::EmbeddingProtocol
- toolkits.memory.protocols.vector::VectorStoreProtocol

[OUTPUT]
- DualLaneIngestPipeline: Main pipeline coordinator

[POS]
Core pipeline coordinator in toolkits.retriever.ingest.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Awaitable, Literal

from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
from myrm_agent_harness.toolkits.retriever.ingest.consumer import BatchEmbedConsumer
from myrm_agent_harness.toolkits.retriever.ingest.tree import DirTreeBuilder
from myrm_agent_harness.toolkits.retriever.ingest.types import (
    Chunk,
    EndOfTask,
    IngestEvent,
    IngestStats,
    TaskEnvelope,
    TaskStatus,
)

logger = logging.getLogger(__name__)


# Type aliases for injected producers and summarizers
ObjectProducerFunc = Callable[[str], AsyncIterator[Chunk] | Awaitable[list[Chunk]]]
DirSummarizerFunc = Callable[[str, list[str], list[str]], Awaitable[str | None]]


class DualLaneIngestPipeline:
    """High-throughput dual-lane ingest coordinator with bounded backpressure."""

    def __init__(
        self,
        embedder: EmbeddingProtocol,
        vector_store: VectorStoreProtocol,
        collection_name: str,
        *,
        max_queue_size: int = 200,
        batch_size: int = 32,
        max_parallel_workers: int = 4,
        idle_flush_timeout_seconds: float = 2.0,
        on_event: Callable[[IngestEvent], None] | None = None,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._collection_name = collection_name
        self._max_queue_size = max(10, max_queue_size)
        self._batch_size = max(1, batch_size)
        self._max_parallel_workers = max(1, max_parallel_workers)
        self._idle_timeout = idle_flush_timeout_seconds
        self._on_event = on_event

        self._queue: asyncio.Queue[TaskEnvelope | None] = asyncio.Queue(maxsize=self._max_queue_size)
        self._stats = IngestStats()
        self._tree_builder = DirTreeBuilder()

    def _emit_event(
        self,
        event_type: Literal[
            "object_start",
            "object_success",
            "object_failed",
            "dir_summarized",
            "embed_batch_flushed",
            "pipeline_completed",
        ],
        uri: str | None = None,
        message: str = "",
    ) -> None:
        if self._on_event:
            self._on_event(
                IngestEvent(
                    event_type=event_type,
                    uri=uri,
                    message=message,
                    stats=self._stats,
                )
            )

    async def run(
        self,
        object_uris: list[str],
        object_producer: ObjectProducerFunc,
        dir_summarizer: DirSummarizerFunc | None = None,
    ) -> IngestStats:
        """Execute dual-lane ingestion over the provided list of object URIs."""
        start_time = time.monotonic()
        self._stats = IngestStats(total_objects=len(object_uris))
        self._tree_builder = DirTreeBuilder()

        # Build initial directory DAG
        for uri in object_uris:
            self._tree_builder.add_object(uri)
        initial_leaf_dirs = self._tree_builder.finalize()

        # Start BatchEmbedConsumer background worker
        consumer = BatchEmbedConsumer(
            queue=self._queue,
            embedder=self._embedder,
            vector_store=self._vector_store,
            collection_name=self._collection_name,
            batch_size=self._batch_size,
            idle_flush_timeout_seconds=self._idle_timeout,
            stats=self._stats,
            on_batch_flushed=lambda count: self._emit_event(
                "embed_batch_flushed", message=f"Flushed batch of {count} vectors"
            ),
        )
        consumer_task = asyncio.create_task(consumer.run())

        try:
            # Run Object Lane and Job Lane concurrently
            await asyncio.gather(
                self._run_object_lane(object_uris, object_producer),
                self._run_job_lane(initial_leaf_dirs, dir_summarizer),
            )

            # Wait until all items in queue are consumed
            await self._queue.join()

        finally:
            # Send poison pill to stop consumer gracefully
            await self._queue.put(None)
            await consumer_task

        self._stats.duration_seconds = time.monotonic() - start_time
        self._emit_event("pipeline_completed", message="Pipeline finished successfully")
        return self._stats

    async def _run_object_lane(
        self,
        object_uris: list[str],
        producer_func: ObjectProducerFunc,
    ) -> None:
        """Object Lane: Process files concurrently with Semaphore throttling."""
        semaphore = asyncio.Semaphore(self._max_parallel_workers)

        async def _process_single_object(uri: str) -> None:
            async with semaphore:
                self._emit_event("object_start", uri=uri)
                task_id = f"task:{uri}"
                chunks_count = 0
                try:
                    res = producer_func(uri)
                    if hasattr(res, "__aiter__"):
                        async for chunk in res:
                            chunks_count += 1
                            self._stats.total_chunks_produced += 1
                            # Backpressure happens here if queue is full!
                            await self._queue.put(TaskEnvelope(task_id=task_id, payload=chunk))
                    else:
                        chunks = await res
                        for chunk in chunks:
                            chunks_count += 1
                            self._stats.total_chunks_produced += 1
                            await self._queue.put(TaskEnvelope(task_id=task_id, payload=chunk))

                    await self._queue.put(
                        TaskEnvelope(
                            task_id=task_id,
                            payload=EndOfTask(
                                uri=uri,
                                status=TaskStatus.SUCCESS,
                                chunks_produced=chunks_count,
                            ),
                        )
                    )
                    self._emit_event("object_success", uri=uri)

                except Exception as err:
                    logger.warning("Object Lane processing failed for %s: %s", uri, err)
                    await self._queue.put(
                        TaskEnvelope(
                            task_id=task_id,
                            payload=EndOfTask(
                                uri=uri,
                                status=TaskStatus.FAILED,
                                error_message=str(err),
                                chunks_produced=chunks_count,
                            ),
                        )
                    )
                    self._emit_event("object_failed", uri=uri, message=str(err))

        tasks = [asyncio.create_task(_process_single_object(u)) for u in object_uris]
        if tasks:
            await asyncio.gather(*tasks)

    async def _run_job_lane(
        self,
        ready_dirs: list[str],
        summarizer_func: DirSummarizerFunc | None,
    ) -> None:
        """Job Lane: Bottom-up topological directory summarization."""
        if not summarizer_func or not ready_dirs:
            return

        queue: asyncio.Queue[str] = asyncio.Queue()
        for d in ready_dirs:
            queue.put_nowait(d)

        while not queue.empty():
            dir_path = await queue.get()
            node = self._tree_builder.get_node(dir_path)
            if not node:
                queue.task_done()
                continue

            # Gather summaries of child directories
            child_dir_summaries: list[str] = []
            for child_d in node.children_dirs:
                c_node = self._tree_builder.get_node(child_d)
                if c_node and c_node.summary_text:
                    child_dir_summaries.append(c_node.summary_text)

            try:
                summary_text = await summarizer_func(
                    dir_path,
                    node.children_files,
                    child_dir_summaries,
                )
                if summary_text:
                    node.summary_text = summary_text
                    self._stats.total_directories_summarized += 1
                    # Enqueue summary as a Chunk into the bounded queue
                    summary_chunk = Chunk(
                        content=summary_text,
                        uri=f"dir://{dir_path}",
                        metadata={"dir_path": dir_path, "type": "directory_summary"},
                        is_summary=True,
                    )
                    await self._queue.put(
                        TaskEnvelope(task_id=f"job_dir:{dir_path}", payload=summary_chunk)
                    )
                    self._emit_event("dir_summarized", uri=dir_path)

                # Check if parent directory is now ready for bottom-up summarization
                parent_ready = self._tree_builder.on_directory_summarized(
                    dir_path, summary_text or ""
                )
                if parent_ready:
                    queue.put_nowait(parent_ready)

            except Exception as err:
                logger.warning("Job Lane failed summarizing directory %s: %s", dir_path, err)
            finally:
                queue.task_done()
