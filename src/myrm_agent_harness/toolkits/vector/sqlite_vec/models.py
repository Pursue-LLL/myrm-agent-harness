"""Data models and configuration for SQLite vector storage engine.

[POS]
Defines typed configuration and domain models for the embedded single-file
SQLite vector store with dual-track adaptive engine and temporal decay support.

[INPUT]
- pydantic (BaseModel, Field)
- myrm_agent_harness.toolkits.vector.base (VectorDocument, SearchResult)

[OUTPUT]
- SqliteVecEngineMode: Enum of active engine track (native_vec0 or process_blob)
- SqliteVecConfig: Pydantic configuration model
- SqliteVecRecord: Raw storage row entity representation
- DecayedSearchResult: Similarity result enriched with temporal decay metrics
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument


class SqliteVecEngineMode(StrEnum):
    """Execution engine track for SQLite vector store operations."""

    NATIVE_VEC0 = "native_vec0"
    """Track A: Hardware-accelerated sqlite-vec C-extension using vec0 virtual table."""

    PROCESS_BLOB = "process_blob"
    """Track B: Self-contained zero-dependency compact BLOB storage with in-process cosine math."""


class SqliteVecConfig(BaseModel):
    """Configuration options for single-file embedded SQLite vector store."""

    db_path: str = Field(
        default="./data/memory_vector.db",
        description="File path for single-file SQLite database storage.",
    )
    enable_vec_extension: bool = Field(
        default=True,
        description="Whether to attempt loading native sqlite-vec extension (Track A).",
    )
    vec_extension_path: str | None = Field(
        default=None,
        description="Explicit filesystem path to sqlite-vec dynamic library if non-standard.",
    )
    wal_mode: bool = Field(
        default=True,
        description="Enable Write-Ahead Logging for high concurrency read/write isolation.",
    )
    synchronous: Literal["NORMAL", "FULL", "OFF"] = Field(
        default="NORMAL",
        description="SQLite synchronous PRAGMA level for balanced durability and latency.",
    )
    default_half_life_seconds: float = Field(
        default=604800.0,
        ge=60.0,
        description="Default temporal decay half-life in seconds (default: 7 days).",
    )
    floor_score: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Minimum score floor to prevent high-importance memories from dropping to 0.",
    )
    busy_timeout_ms: int = Field(
        default=5000,
        ge=100,
        description="SQLite busy timeout in milliseconds when acquiring write lock.",
    )

    def resolved_path(self) -> Path:
        """Resolve and expand file system path."""
        path = Path(self.db_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


class SqliteVecRecord(BaseModel):
    """Internal database row representation."""

    id: str = Field(description="Unique document identifier.")
    collection: str = Field(description="Target collection or partition name.")
    content: str = Field(description="Raw text content of the document.")
    metadata_json: str = Field(default="{}", description="JSON-serialized document metadata.")
    created_at_epoch: float = Field(description="Unix timestamp epoch of creation.")
    updated_at_epoch: float = Field(description="Unix timestamp epoch of last modification.")
    importance_weight: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="Significance weight multiplier for temporal decay resistance.",
    )


class DecayedSearchResult(BaseModel):
    """Enriched search result incorporating time decay factor."""

    document: VectorDocument
    raw_similarity: float = Field(description="Cosine similarity score before decay.")
    decay_factor: float = Field(description="Applied temporal decay multiplier in (floor, 1.0].")
    decayed_score: float = Field(description="Final ranking score after temporal decay.")

    @classmethod
    def from_search_result(
        cls,
        base_result: SearchResult,
        raw_sim: float,
        decay_fac: float,
    ) -> DecayedSearchResult:
        """Construct decayed search result from base result."""
        return cls(
            document=base_result.document,
            raw_similarity=raw_sim,
            decay_factor=decay_fac,
            decayed_score=base_result.score,
        )
