"""Data models for local file search toolkit.

[INPUT]
(none — leaf module)

[OUTPUT]
- IndexedDirectory: User-configured directory for indexing
- FileRecord: Metadata record for an indexed file
- IndexStats: Aggregated statistics for the index
- SearchResult: A single search hit with score and metadata
- SearchResponse: Complete search response with results and metadata

[POS]
Core data models for the local file search toolkit. All persistence-ready via Pydantic,
all types explicit — no Any.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class IndexStatus(StrEnum):
    """Status of the indexing process."""

    IDLE = "idle"
    INDEXING = "indexing"
    FAILED = "failed"


class IndexedDirectory(BaseModel):
    """A user-configured directory to be indexed for local file search."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    path: str = Field(description="Absolute path to the directory")
    recursive: bool = Field(default=True, description="Whether to index subdirectories")
    enabled: bool = Field(default=True, description="Whether this directory is active for indexing")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FileRecord(BaseModel):
    """Metadata record for a single indexed file."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    path: str = Field(description="Absolute file path")
    relative_path: str = Field(description="Path relative to the indexed directory root")
    directory_id: str = Field(description="ID of the parent IndexedDirectory")
    content_hash: str = Field(description="SHA256 hash of file content for incremental updates")
    file_size: int = Field(description="File size in bytes")
    file_type: str = Field(description="File extension without dot (e.g. 'pdf', 'docx')")
    chunk_count: int = Field(default=0, description="Number of text chunks stored in vector DB")
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = Field(default=None, description="Last indexing error, if any")


class IndexStats(BaseModel):
    """Aggregated index statistics."""

    total_files: int = 0
    total_chunks: int = 0
    total_directories: int = 0
    status: IndexStatus = IndexStatus.IDLE
    last_indexed_at: datetime | None = None
    indexing_progress: float = Field(default=0.0, ge=0.0, le=1.0, description="0.0 to 1.0")
    current_file: str | None = Field(default=None, description="Currently indexing file path")
    error_count: int = 0


class SearchHit(BaseModel):
    """A single search result with relevance score."""

    file_path: str = Field(description="Absolute path to the source file")
    relative_path: str = Field(description="Path relative to the indexed directory")
    snippet: str = Field(description="Relevant text snippet from the file")
    score: float = Field(description="Relevance score (higher is better)")
    file_type: str = Field(description="File type (e.g. 'pdf', 'docx')")
    section: str = Field(default="", description="Section/heading context if available")


class SearchResponse(BaseModel):
    """Complete search response."""

    hits: list[SearchHit] = Field(default_factory=list)
    total_hits: int = 0
    query: str = ""
    search_time_ms: float = 0.0
