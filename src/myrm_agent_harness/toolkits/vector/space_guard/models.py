"""Data contracts and exceptions for vector space consistency guard.

[POS]
Embedded data models for model fingerprinting, vector space metadata,
validation results, and graceful fallback decisions.

[INPUT]
- datetime, hashlib, pydantic, typing

[OUTPUT]
- EmbeddingModelFingerprint, VectorSpaceMetadata, VectorSpaceValidationResult
- ReindexStatusReport, VectorSpaceMismatchError, VectorSpaceDimensionMismatchError
- VectorSpaceBaseMismatchError
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class VectorSpaceMismatchError(Exception):
    """Base exception raised when vector space consistency check fails."""

    def __init__(
        self,
        message: str,
        expected: EmbeddingModelFingerprint | None = None,
        actual: EmbeddingModelFingerprint | None = None,
    ) -> None:
        super().__init__(message)
        self.expected = expected
        self.actual = actual


class VectorSpaceDimensionMismatchError(VectorSpaceMismatchError):
    """Raised when query/document vector dimension does not match collection space."""


class VectorSpaceBaseMismatchError(VectorSpaceMismatchError):
    """Raised when vector dimensions match but underlying embedding model bases differ."""


class EmbeddingModelFingerprint(BaseModel):
    """Strongly typed fingerprint identifying an embedding model and vector space configuration."""

    provider_id: str = Field(
        description="Identifier of embedding provider, e.g. openai, ollama, voyage"
    )
    model_name: str = Field(
        description="Name of embedding model, e.g. text-embedding-3-small, bge-m3"
    )
    vector_dimension: int = Field(gt=0, description="Dense vector coordinate dimension")
    metric_type: Literal["cosine", "dot", "euclidean"] = Field(
        default="cosine", description="Distance metric used for ANN search"
    )
    config_hash: str = Field(
        default="", description="Deterministic SHA256 signature of provider, model, dim, and metric"
    )

    def model_post_init(self, __context: object) -> None:
        """Automatically compute config_hash if omitted or empty."""
        if not self.config_hash:
            canonical_repr = (
                f"{self.provider_id.strip().lower()}:"
                f"{self.model_name.strip().lower()}:"
                f"{self.vector_dimension}:"
                f"{self.metric_type.strip().lower()}"
            )
            object.__setattr__(
                self,
                "config_hash",
                hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()[:16],
            )

    def is_compatible_with(self, other: EmbeddingModelFingerprint) -> tuple[bool, str]:
        """Check mathematical and semantic compatibility with another fingerprint."""
        if self.vector_dimension != other.vector_dimension:
            return (
                False,
                f"Dimension mismatch: expected {self.vector_dimension}, got {other.vector_dimension}",
            )
        if (
            self.provider_id.strip().lower() != other.provider_id.strip().lower()
            or self.model_name.strip().lower() != other.model_name.strip().lower()
        ):
            return (
                False,
                f"Model base mismatch: collection indexed with {self.provider_id}/{self.model_name}, "
                f"query issued with {other.provider_id}/{other.model_name}",
            )
        if self.metric_type != other.metric_type:
            return (
                False,
                f"Metric mismatch: collection metric is {self.metric_type}, query uses {other.metric_type}",
            )
        return True, "Consistent vector space"


class VectorSpaceMetadata(BaseModel):
    """Persistent metadata binding a vector collection to its canonical model fingerprint."""

    collection_name: str = Field(description="Target vector store collection name")
    fingerprint: EmbeddingModelFingerprint = Field(
        description="Canonical model fingerprint for this collection"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when space was established",
    )
    last_validated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of latest successful consistency verification",
    )
    total_vectors_indexed: int = Field(default=0, ge=0, description="Indexed vector count")


class VectorSpaceValidationResult(BaseModel):
    """Outcome of pre-flight vector space consistency verification."""

    is_valid: bool = Field(description="True if safe to proceed with vector operations")
    status: Literal[
        "consistent",
        "dimension_mismatch",
        "model_base_mismatch",
        "uninitialized",
        "metadata_missing",
    ] = Field(description="Granular verification status code")
    message: str = Field(description="Human-readable verification diagnostic message")
    expected_fingerprint: EmbeddingModelFingerprint | None = Field(
        default=None, description="Registered collection fingerprint"
    )
    current_fingerprint: EmbeddingModelFingerprint | None = Field(
        default=None, description="Runtime model fingerprint being evaluated"
    )
    recommended_action: Literal[
        "proceed", "reindex_required", "initialize_space", "fallback_fts"
    ] = Field(description="Prescribed handling strategy for runtime caller")


class ReindexStatusReport(BaseModel):
    """Progress and execution status for vector space re-indexing."""

    collection_name: str = Field(description="Target collection name")
    previous_fingerprint: EmbeddingModelFingerprint | None = Field(
        default=None, description="Previous model fingerprint"
    )
    target_fingerprint: EmbeddingModelFingerprint = Field(
        description="New target model fingerprint"
    )
    reindexed_count: int = Field(default=0, ge=0, description="Count of successfully re-indexed items")
    status: Literal["idle", "in_progress", "completed", "failed"] = Field(
        default="idle", description="Reindex pipeline status"
    )
    error_message: str | None = Field(default=None, description="Error details if reindex failed")
