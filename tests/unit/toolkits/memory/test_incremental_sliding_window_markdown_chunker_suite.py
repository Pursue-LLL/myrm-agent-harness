"""Unit tests for Item 132 Incremental Sliding Window Markdown Chunker Suite.

[POS]
Unit test suite verifying 400-token sliding window slicing, 80-token overlap,
fenced code block integrity, line-level hydration, and incremental diff pipeline.

[INPUT]
- pytest, pytest_asyncio
- myrm_agent_harness.toolkits.memory.chunking (
    ChunkSourceHydrator,
    ChunkingConfig,
    IncrementalIndexingPipeline,
    MarkdownChunk,
    MarkdownSlidingWindowChunker,
  )

[OUTPUT]
- Test cases covering chunker semantics and incremental caching.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.chunking import (
    ChunkingConfig,
    ChunkSourceHydrator,
    IncrementalIndexingPipeline,
    MarkdownSlidingWindowChunker,
)


@pytest.fixture
def sample_markdown() -> str:
    """Fixture providing structured Markdown text with headings and code blocks."""
    return """# Memory Architecture Overview

This is the introductory section explaining the persistent long-term memory system.
Agents must maintain facts, preferences, and procedural experience across sessions.

## Sliding Window Chunking

When documents grow large, standard fixed chunkers cut sentences awkwardly in half.
The sliding window technique maintains semantic overlap so that transitions stay intact.
Each chunk contains about 400 tokens with an 80 token overlap budget for continuity.

```python
def retrieve_relevant_facts(query: str, top_k: int = 5):
    # This code block should remain atomic and protected
    results = vector_store.search(query, limit=top_k)
    return [r.content for r in results]
```

### Lineage and Pointers

Every slice maintains 1-indexed start_line and end_line pointers pointing back to source.
This allows subsequent hydration and exact diffing across file edits.
"""


def test_chunker_basic_sliding_window_and_line_pointers(sample_markdown: str) -> None:
    """Verify chunker slices document into valid chunks with valid line indices and hashes."""
    config = ChunkingConfig(target_tokens=50, overlap_tokens=15, chars_per_token=3.5)
    chunker = MarkdownSlidingWindowChunker(config)

    chunks = chunker.chunk_document(sample_markdown, source_path="MEMORY.md")
    assert len(chunks) >= 2

    for chk in chunks:
        assert chk.source_path == "MEMORY.md"
        assert chk.start_line >= 1
        assert chk.end_line >= chk.start_line
        assert chk.char_start >= 0
        assert chk.char_end > chk.char_start
        assert len(chk.text) > 0
        assert len(chk.chunk_hash) == 16
        assert chk.token_estimate > 0


def test_chunker_preserves_code_block_integrity() -> None:
    """Verify that fenced code blocks are protected from being split prematurely."""
    markdown_with_code = """# Code Test

```typescript
interface MemoryRecord {
  id: string;
  payload: Record<string, string>;
  created_at: string;
}
```

Trailing documentation text following the interface declaration.
"""
    config = ChunkingConfig(target_tokens=10, overlap_tokens=2, chars_per_token=3.5)
    chunker = MarkdownSlidingWindowChunker(config)

    chunks = chunker.chunk_document(markdown_with_code, source_path="types.md")
    # Code block should be retained intact within one chunk
    code_chunk_found = any("interface MemoryRecord" in c.text and "created_at: string;" in c.text for c in chunks)
    assert code_chunk_found is True


def test_chunk_source_hydrator_expansion(sample_markdown: str) -> None:
    """Verify hydrator reconstructs surrounding context lines using line pointers."""
    config = ChunkingConfig(target_tokens=30, overlap_tokens=5)
    chunker = MarkdownSlidingWindowChunker(config)
    chunks = chunker.chunk_document(sample_markdown, source_path="MEMORY.md")

    target_chunk = chunks[1]
    hydrated = ChunkSourceHydrator.hydrate_context(
        chunk=target_chunk, full_document=sample_markdown, window_lines=2
    )

    assert target_chunk.text in hydrated
    # Hydrated context should span at least as many or more lines than original chunk
    assert len(hydrated.splitlines()) >= (target_chunk.end_line - target_chunk.start_line + 1)


@pytest.mark.asyncio
async def test_incremental_pipeline_first_run_and_subsequent_reuse(sample_markdown: str) -> None:
    """Verify that identical content achieves 100% token savings upon re-indexing."""
    pipeline = IncrementalIndexingPipeline(
        config=ChunkingConfig(target_tokens=40, overlap_tokens=10)
    )

    mock_embeddings_called = 0

    def mock_embedder(texts: list[str]) -> list[list[float]]:
        nonlocal mock_embeddings_called
        mock_embeddings_called += len(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]

    # 1. First run -> full index
    report1, chunks1, embeddings1 = await pipeline.diff_and_index(
        source_path="MEMORY.md",
        new_content=sample_markdown,
        embedder=mock_embedder,
    )
    assert report1.status == "fully_reindexed"
    assert report1.reused_chunks == 0
    assert report1.changed_chunks == len(chunks1)
    assert report1.token_savings_pct == 0.0
    assert mock_embeddings_called == len(chunks1)
    assert len(embeddings1) == len(chunks1)

    # 2. Second run with unchanged content -> 100% token savings
    mock_embeddings_called = 0
    report2, chunks2, embeddings2 = await pipeline.diff_and_index(
        source_path="MEMORY.md",
        new_content=sample_markdown,
        embedder=mock_embedder,
    )
    assert report2.status == "unchanged"
    assert report2.reused_chunks == len(chunks2)
    assert report2.changed_chunks == 0
    assert report2.token_savings_pct == 100.0
    assert mock_embeddings_called == 0
    assert len(embeddings2) == len(chunks2)


@pytest.mark.asyncio
async def test_incremental_pipeline_partial_update(sample_markdown: str) -> None:
    """Verify appending new section reuses previous chunks and saves partial tokens."""
    pipeline = IncrementalIndexingPipeline(
        config=ChunkingConfig(target_tokens=40, overlap_tokens=10)
    )

    def mock_embedder(texts: list[str]) -> list[list[float]]:
        return [[0.05 * i for _ in range(4)] for i in range(len(texts))]

    # Initial index
    _report1, chunks1, _ = await pipeline.diff_and_index(
        source_path="MEMORY.md",
        new_content=sample_markdown,
        embedder=mock_embedder,
    )

    # Append a new section to simulate user editing notes
    appended_content = sample_markdown + "\n\n## Brand New Section\n\nThis is newly added text that requires new embedding.\n"

    report2, chunks2, _ = await pipeline.diff_and_index(
        source_path="MEMORY.md",
        new_content=appended_content,
        embedder=mock_embedder,
    )

    assert report2.status == "partially_updated"
    assert report2.reused_chunks > 0
    assert report2.changed_chunks >= 1
    assert report2.token_savings_pct > 0.0
    assert len(chunks2) >= len(chunks1)
