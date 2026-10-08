"""Data models for incremental sliding window Markdown chunker.

[POS]
Core contracts for semantic Markdown chunks, sliding window configuration,
content hash indexing, and incremental diff reports.

[INPUT]
- datetime, hashlib, pydantic, typing

[OUTPUT]
- ChunkingConfig, IncrementalDiffReport, MarkdownChunk
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChunkingConfig(BaseModel):
    """Configuration for sliding window Markdown chunking."""

    target_tokens: int = Field(default=400, gt=0, description="Target token budget per chunk")
    overlap_tokens: int = Field(
        default=80, ge=0, description="Overlap token budget across consecutive chunks"
    )
    chars_per_token: float = Field(
        default=3.5, gt=0.0, description="Heuristic character-to-token ratio"
    )
    max_chunk_chars: int = Field(
        default=2400, gt=0, description="Hard cap for single chunk characters to prevent DoS"
    )

    @property
    def target_chars(self) -> int:
        """Calculate target character length for single chunk."""
        return int(self.target_tokens * self.chars_per_token)

    @property
    def overlap_chars(self) -> int:
        """Calculate overlap character length."""
        return int(self.overlap_tokens * self.chars_per_token)


class MarkdownChunk(BaseModel):
    """Structured Markdown chunk with source line pointers and content hash."""

    chunk_id: str = Field(description="Unique identifier for chunk")
    source_path: str = Field(description="Origin document file path or identifier")
    start_line: int = Field(ge=1, description="1-based starting line number in source")
    end_line: int = Field(ge=1, description="1-based ending line number in source")
    char_start: int = Field(ge=0, description="0-based character start index in source")
    char_end: int = Field(ge=0, description="0-based character end index in source")
    text: str = Field(description="Chunk textual content")
    chunk_hash: str = Field(default="", description="Deterministic SHA256 prefix of text")
    token_estimate: int = Field(default=0, ge=0, description="Estimated token count")
    is_truncated: bool = Field(default=False, description="True if truncated by max character cap")

    def model_post_init(self, __context: object) -> None:
        """Automatically compute chunk_hash if empty."""
        if not self.chunk_hash:
            normalized = self.text.strip()
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
            object.__setattr__(self, "chunk_hash", digest)


class IncrementalDiffReport(BaseModel):
    """Report detailing incremental chunk diff and token savings."""

    source_path: str = Field(description="Target document path")
    total_chunks: int = Field(ge=0, description="Total chunks in updated document")
    reused_chunks: int = Field(ge=0, description="Count of identical chunks reused from cache")
    changed_chunks: int = Field(ge=0, description="Count of new or modified chunks needing embedding")
    deleted_chunks: int = Field(ge=0, description="Count of obsolete chunks removed")
    token_savings_pct: float = Field(
        ge=0.0, le=100.0, description="Percentage of embedding API tokens saved via reuse"
    )
    status: Literal["unchanged", "partially_updated", "fully_reindexed"] = Field(
        default="partially_updated", description="Diff outcome status"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Diff calculation timestamp",
    )
