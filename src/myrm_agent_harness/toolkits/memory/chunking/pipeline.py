"""Incremental Markdown chunking and indexing pipeline.

[POS]
Orchestration pipeline computing content hashes, detecting delta modifications,
reusing cached vector embeddings, and avoiding redundant API consumption.

[INPUT]
- collections.abc.Callable, collections.abc.Sequence
- .models (ChunkingConfig, IncrementalDiffReport, MarkdownChunk)
- .chunker (MarkdownSlidingWindowChunker)

[OUTPUT]
- IncrementalIndexingPipeline
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.chunking.chunker import (
    MarkdownSlidingWindowChunker,
)
from myrm_agent_harness.toolkits.memory.chunking.models import (
    ChunkingConfig,
    IncrementalDiffReport,
    MarkdownChunk,
)


class IncrementalIndexingPipeline:
    """Manages incremental chunk diffing and selective embedding calculation."""

    def __init__(
        self,
        config: ChunkingConfig | None = None,
        chunker: MarkdownSlidingWindowChunker | None = None,
    ) -> None:
        """Initialize indexing pipeline."""
        self.config: ChunkingConfig = config or ChunkingConfig()
        self.chunker: MarkdownSlidingWindowChunker = chunker or MarkdownSlidingWindowChunker(
            self.config
        )
        # In-memory index cache: source_path -> (dict[chunk_hash, tuple[MarkdownChunk, list[float]]])
        self._cache: dict[str, dict[str, tuple[MarkdownChunk, list[float]]]] = {}

    def get_cached_chunks(self, source_path: str) -> list[MarkdownChunk]:
        """Retrieve currently cached chunks for a source path."""
        entries = self._cache.get(source_path, {})
        return [chunk for chunk, _ in entries.values()]

    def clear_cache(self, source_path: str | None = None) -> None:
        """Clear cache for specified source or all sources."""
        if source_path is not None:
            self._cache.pop(source_path, None)
        else:
            self._cache.clear()

    async def diff_and_index(
        self,
        source_path: str,
        new_content: str,
        embedder: Callable[[Sequence[str]], Sequence[list[float]]] | None = None,
    ) -> tuple[IncrementalDiffReport, list[MarkdownChunk], list[list[float]]]:
        """Perform incremental sliding window chunking and diff against existing cache.

        Args:
            source_path: Source document identifier.
            new_content: Fresh document content.
            embedder: Optional callable computing embeddings for modified chunks.

        Returns:
            Tuple of (IncrementalDiffReport, all_chunks, all_embeddings).
        """
        new_chunks = self.chunker.chunk_document(new_content, source_path=source_path)
        existing_map = self._cache.get(source_path, {})

        reused_count = 0
        reused_tokens = 0
        total_tokens = sum(c.token_estimate for c in new_chunks)

        chunks_needing_embedding: list[MarkdownChunk] = []
        result_chunks: list[MarkdownChunk] = []
        result_embeddings: list[list[float]] = []

        # Identify which chunks can reuse embeddings vs require re-embedding
        for chk in new_chunks:
            result_chunks.append(chk)
            if chk.chunk_hash in existing_map:
                reused_count += 1
                reused_tokens += chk.token_estimate
                _cached_chunk, cached_vec = existing_map[chk.chunk_hash]
                result_embeddings.append(cached_vec)
            else:
                chunks_needing_embedding.append(chk)
                # Placeholder, will be replaced after embedder run
                result_embeddings.append([])

        # Calculate new embeddings for delta chunks
        if chunks_needing_embedding and embedder is not None:
            texts = [c.text for c in chunks_needing_embedding]
            computed_vectors = list(embedder(texts))
            if len(computed_vectors) != len(texts):
                raise ValueError(
                    f"Embedder returned {len(computed_vectors)} vectors for {len(texts)} chunks"
                )

            # Insert computed vectors into their respective slots
            compute_idx = 0
            for i, _chk in enumerate(result_chunks):
                if not result_embeddings[i]:
                    result_embeddings[i] = computed_vectors[compute_idx]
                    compute_idx += 1

        changed_count = len(chunks_needing_embedding)
        deleted_count = max(0, len(existing_map) - reused_count)
        savings_pct = (reused_tokens / total_tokens * 100.0) if total_tokens > 0 else 0.0

        if changed_count == 0 and deleted_count == 0:
            status = "unchanged"
        elif reused_count == 0:
            status = "fully_reindexed"
        else:
            status = "partially_updated"

        report = IncrementalDiffReport(
            source_path=source_path,
            total_chunks=len(new_chunks),
            reused_chunks=reused_count,
            changed_chunks=changed_count,
            deleted_chunks=deleted_count,
            token_savings_pct=round(savings_pct, 2),
            status=status,
            timestamp=datetime.now(UTC),
        )

        # Update cache atomically
        new_cache_map: dict[str, tuple[MarkdownChunk, list[float]]] = {}
        for chk, vec in zip(result_chunks, result_embeddings, strict=False):
            new_cache_map[chk.chunk_hash] = (chk, vec)
        self._cache[source_path] = new_cache_map

        return report, result_chunks, result_embeddings
