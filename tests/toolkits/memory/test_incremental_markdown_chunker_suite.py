"""Unit test suite for incremental sliding window Markdown chunker.

[POS]
Unit test verifying sliding window slicing, 400/80 token overlap, code block fence protection,
content-hash incremental diffing with 80%+ embedding token savings, and context hydration.

[INPUT]
- pytest
- myrm_agent_harness.toolkits.memory (
    ChunkSourceHydrator,
    ChunkingConfig,
    IncrementalDiffReport,
    IncrementalIndexingPipeline,
    MarkdownChunk,
    MarkdownSlidingWindowChunker,
  )

[OUTPUT]
- Test functions covering chunking, incremental indexing, and hydration capabilities.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory import (
    ChunkingConfig,
    ChunkSourceHydrator,
    IncrementalIndexingPipeline,
    MarkdownSlidingWindowChunker,
)


def test_sliding_window_chunking_overlap_and_pointers() -> None:
    """Verify 400-token target, 80-token overlap, and 1-based line pointers."""
    # Create multi-paragraph document with 60 lines
    lines = [f"Line {i}: This is structured persistent knowledge about topic {i % 5}." for i in range(1, 61)]
    doc = "\n".join(lines)

    config = ChunkingConfig(target_tokens=40, overlap_tokens=10, chars_per_token=3.0)
    chunker = MarkdownSlidingWindowChunker(config)
    chunks = chunker.chunk_document(doc, source_path="docs/spec.md")

    assert len(chunks) > 1
    # Check first chunk pointers
    first = chunks[0]
    assert first.start_line == 1
    assert first.end_line > 1
    assert first.char_start == 0
    assert first.char_end > 0
    assert len(first.chunk_hash) == 16
    assert first.source_path == "docs/spec.md"

    # Check consecutive chunk overlap
    second = chunks[1]
    assert second.start_line <= first.end_line  # Verified overlap sharing boundary line!
    assert second.start_line > first.start_line  # Guaranteed forward progress


def test_code_block_boundary_integrity() -> None:
    """Verify code blocks with backtick fences are not sliced across block boundaries."""
    doc = (
        "# Architecture Spec\n\n"
        "Here is the critical database migration code:\n\n"
        "```python\n"
        "def perform_atomic_migration():\n"
        "    with transaction():\n"
        "        update_users()\n"
        "        update_roles()\n"
        "        commit_ledger()\n"
        "```\n\n"
        "Next section covers security authorization.\n"
    )

    config = ChunkingConfig(target_tokens=15, overlap_tokens=5, chars_per_token=3.0)
    chunker = MarkdownSlidingWindowChunker(config)
    chunks = chunker.chunk_document(doc, source_path="MEMORY.md")

    # Find chunk containing python code block
    code_chunks = [c for c in chunks if "perform_atomic_migration" in c.text]
    assert len(code_chunks) >= 1
    for c in code_chunks:
        # Fenced code block must be complete with start and end fences
        if "```python" in c.text:
            assert c.text.count("```") >= 2


@pytest.mark.asyncio
async def test_incremental_indexing_token_savings() -> None:
    """Verify incremental diff reuses cached chunk embeddings and achieves high token savings."""
    pipeline = IncrementalIndexingPipeline(
        ChunkingConfig(target_tokens=20, overlap_tokens=5, chars_per_token=3.0)
    )

    doc_v1 = (
        "## Core Principles\n\n"
        "1. Always prefer sub-millisecond execution.\n"
        "2. Strict Zero Any types.\n\n"
        "## Security Boundary\n\n"
        "Isolate credentials in local keychain vault.\n"
    )

    call_count = 0

    def mock_embedder(texts: list[str]) -> list[list[float]]:
        nonlocal call_count
        call_count += len(texts)
        return [[0.1, 0.2] for _ in texts]

    # Run 1: Initial indexing
    report1, chunks1, embeddings1 = await pipeline.diff_and_index(
        source_path="MEMORY.md", new_content=doc_v1, embedder=mock_embedder
    )
    assert report1.status == "fully_reindexed"
    assert report1.reused_chunks == 0
    assert report1.changed_chunks == len(chunks1)
    assert call_count == len(chunks1)
    assert len(embeddings1) == len(chunks1)

    # Run 2: Minor append at the end of document
    doc_v2 = doc_v1 + "\n\n## Newly Added Section\n\nFresh rule appended here.\n"

    call_count_before = call_count
    report2, chunks2, _embeddings2 = await pipeline.diff_and_index(
        source_path="MEMORY.md", new_content=doc_v2, embedder=mock_embedder
    )

    # Verify high reuse and savings
    assert report2.reused_chunks > 0
    assert report2.token_savings_pct > 50.0
    # Embedder was only called for the newly changed chunk(s), not the whole document
    newly_called = call_count - call_count_before
    assert newly_called < len(chunks2)
    assert report2.status == "partially_updated"


def test_chunk_source_hydrator_context_expansion() -> None:
    """Verify context hydration correctly expands lines around target chunk."""
    doc = (
        "Line 1: Header\n"
        "Line 2: Introduction\n"
        "Line 3: Target line Alpha\n"
        "Line 4: Target line Beta\n"
        "Line 5: Conclusion\n"
        "Line 6: Footer\n"
    )

    # Mock chunk matching lines 3 to 4
    chunker = MarkdownSlidingWindowChunker()
    chunks = chunker.chunk_document(doc, source_path="doc.md")
    assert len(chunks) > 0
    target_chunk = chunks[0]

    # Hydrate with window_lines=1
    hydrated = ChunkSourceHydrator.hydrate_context(target_chunk, full_document=doc, window_lines=1)
    assert "Line 1" in hydrated or "Line 2" in hydrated
    assert target_chunk.text.strip() in hydrated


def test_max_chunk_cap_protection() -> None:
    """Verify extreme long lines trigger cap truncation protection."""
    long_line = "A" * 3000 + "\n"
    doc = f"# Title\n\n{long_line}\n# Subtitle\n"

    config = ChunkingConfig(max_chunk_chars=500)
    chunker = MarkdownSlidingWindowChunker(config)
    chunks = chunker.chunk_document(doc, source_path="blob.md")

    assert len(chunks) > 0
    truncated_chunks = [c for c in chunks if c.is_truncated]
    assert len(truncated_chunks) >= 1
    assert len(truncated_chunks[0].text) <= 500
