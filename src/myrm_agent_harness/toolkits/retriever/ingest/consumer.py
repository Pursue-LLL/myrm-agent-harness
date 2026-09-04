"""Process-level batch embedding consumer for the ingest pipeline.

Drains the bounded chunks_q across all tasks, batches Chunk instances to `batch_size`
or flushes on idle timeout, invokes the injected EmbeddingProtocol, and upserts
into the injected VectorStoreProtocol.

[INPUT]
- .types::Chunk, TaskEnvelope, EndOfTask
- toolkits.memory.protocols.embedding::EmbeddingProtocol
- toolkits.memory.protocols.vector::VectorStoreProtocol
- toolkits.vector.base::VectorDocument

[OUTPUT]
- BatchEmbedConsumer: High-throughput batch embedding and vector persistence engine

[POS]
Pipeline tail consumer in toolkits.retriever.ingest.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable

from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
from myrm_agent_harness.toolkits.retriever.ingest.types import (
    Chunk,
    EndOfTask,
    IngestStats,
    TaskEnvelope,
    TaskStatus,
)
from myrm_agent_harness.toolkits.vector.base import VectorDocument

logger = logging.getLogger(__name__)


def _generate_doc_id(uri: str, chunk_index: int, is_summary: bool) -> str:
    """Generate a stable deterministic ID for a vector document."""
    prefix = "summary" if is_summary else "chunk"
    raw = f"{prefix}:{uri}:{chunk_index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class BatchEmbedConsumer:
    """Consumes chunks from a bounded queue, batches them, embeds, and writes to vector store."""

    def __init__(
        self,
        queue: asyncio.Queue[TaskEnvelope | None],
        embedder: EmbeddingProtocol,
        vector_store: VectorStoreProtocol,
        collection_name: str,
        *,
        batch_size: int = 32,
        idle_flush_timeout_seconds: float = 2.0,
        stats: IngestStats | None = None,
        on_batch_flushed: Callable[[int], None] | None = None,
    ) -> None:
        self._queue = queue
        self._embedder = embedder
        self._vector_store = vector_store
        self._collection_name = collection_name
        self._batch_size = max(1, batch_size)
        self._idle_timeout = max(0.1, idle_flush_timeout_seconds)
        self._stats = stats or IngestStats()
        self._on_batch_flushed = on_batch_flushed
        self._buffer: list[tuple[str, Chunk]] = []
        self._stop_requested = False

    async def run(self) -> None:
        """Main loop consuming from queue until poison pill (None) is received."""
        while not self._stop_requested:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=self._idle_timeout)
                if item is None:
                    # Poison pill: flush remaining buffer and exit
                    await self._flush_buffer()
                    self._queue.task_done()
                    break

                if isinstance(item.payload, Chunk):
                    self._buffer.append((item.task_id, item.payload))
                    if len(self._buffer) >= self._batch_size:
                        await self._flush_buffer()
                elif isinstance(item.payload, EndOfTask):
                    if item.payload.status == TaskStatus.SUCCESS:
                        self._stats.succeeded_objects += 1
                    elif item.payload.status == TaskStatus.FAILED:
                        self._stats.failed_objects += 1
                    elif item.payload.status == TaskStatus.SKIPPED:
                        self._stats.skipped_objects += 1

                self._queue.task_done()

            except TimeoutError:
                # Idle timeout expired: flush whatever is pending
                if self._buffer:
                    await self._flush_buffer()

        # Final drain guarantee
        if self._buffer:
            await self._flush_buffer()

    async def _flush_buffer(self) -> None:
        """Batch-embed buffered chunks and write to vector store."""
        if not self._buffer:
            return

        batch = list(self._buffer)
        self._buffer.clear()

        texts = [chunk.content for _, chunk in batch]
        try:
            embeddings = await self._embedder.embed_batch(texts)
            documents: list[VectorDocument] = []

            for (task_id, chunk), emb in zip(batch, embeddings, strict=True):
                doc_id = _generate_doc_id(chunk.uri, chunk.chunk_index, chunk.is_summary)
                meta = dict(chunk.metadata)
                meta["uri"] = chunk.uri
                meta["task_id"] = task_id
                meta["chunk_index"] = chunk.chunk_index
                meta["is_summary"] = chunk.is_summary

                documents.append(
                    VectorDocument(
                        id=doc_id,
                        vector=emb,
                        content=chunk.content,
                        metadata=meta,
                    )
                )

            await self._vector_store.upsert(self._collection_name, documents)
            count = len(documents)
            self._stats.total_chunks_embedded += count

            if self._on_batch_flushed:
                self._on_batch_flushed(count)

        except Exception as err:
            logger.error("Failed to flush embed batch of %d items: %s", len(batch), err)
            # Re-raise or record in stats to ensure observability
            raise

    def stop(self) -> None:
        """Signal consumer to stop gracefully."""
        self._stop_requested = True
