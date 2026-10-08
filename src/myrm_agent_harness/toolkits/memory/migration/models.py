"""Data models for multi-platform memory migration and import engine.

[POS]
Strongly-typed schemas for multi-platform memory detection, security policies,
adaptive parsing, deduplication fingerprints, and migration auditing.

[INPUT]
- enum.StrEnum, pydantic.BaseModel, pydantic.Field

[OUTPUT]
- MigrationSourceType, CompetitorSourceKind
- MigrationSecurityPolicy, ExtractedMemoryUnit, NormalizedMemoryPayload
- ChunkedMemoryArtifact, MigrationRunReport, MigrationExecutionReport
- DetectedCompetitorArtifact
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class MigrationSourceType(StrEnum):
    """Supported external memory ecosystems and artifact formats."""

    OPENCLAW = "openclaw"
    HERMES = "hermes"
    CHATGPT_EXPORT = "chatgpt_export"
    CLAUDE_PROJECT = "claude_project"
    MEMOS = "memos"
    MARKDOWN_TREE = "markdown_tree"
    GENERIC_JSON = "generic_json"


# Alias for backward compatibility across existing competitor migration references
CompetitorSourceKind = MigrationSourceType


class MigrationSecurityPolicy(BaseModel):
    """Security bounds and prompt sanitization settings for external asset imports."""

    max_file_size_bytes: int = Field(
        default=15 * 1024 * 1024, gt=0, description="Maximum single file size (15MB default)"
    )
    max_batch_bytes: int = Field(
        default=100 * 1024 * 1024, gt=0, description="Maximum total batch size (100MB default)"
    )
    sanitize_prompt_injection: bool = Field(
        default=True, description="Whether to filter prompt injection and override directives"
    )
    max_content_chars_per_item: int = Field(
        default=50000, gt=0, description="Upper bound character cap per extracted memory item"
    )


class ExtractedMemoryUnit(BaseModel):
    """A canonical extracted memory fact or entry categorized into cognitive layers."""

    source_type: MigrationSourceType = Field(description="Origin platform ecosystem")
    source_id: str = Field(description="Unique entry or line pointer identifier in origin file")
    raw_snippet: str = Field(description="Raw source text before cleansing")
    normalized_text: str = Field(description="Cleansed, readable memory fact text")
    layer: str = Field(
        default="semantic",
        description="Assigned cognitive layer: profile, semantic, procedural, or episodic",
    )
    tags: list[str] = Field(default_factory=list, description="Extracted category or topic tags")
    content_hash: str = Field(description="Deterministic SHA-256 fingerprint for deduplication")
    provenance: dict[str, str] = Field(
        default_factory=dict, description="Audit provenance key-value pairs"
    )


# Alias for existing code consuming NormalizedMemoryPayload
class NormalizedMemoryPayload(ExtractedMemoryUnit):
    """Backward compatible alias exposing source_kind and layer_recommendation."""

    @property
    def source_kind(self) -> MigrationSourceType:
        return self.source_type

    @property
    def normalized_content(self) -> str:
        return self.normalized_text

    @property
    def raw_content(self) -> str:
        return self.raw_snippet

    @property
    def layer_recommendation(self) -> str:
        return self.layer

    @property
    def provenance_meta(self) -> dict[str, str]:
        return self.provenance


class ChunkedMemoryArtifact(BaseModel):
    """Memory unit paired with sliding-window chunk representations."""

    unit_id: str = Field(description="Identifier of parent extracted memory unit")
    layer: str = Field(description="Cognitive memory layer")
    chunk_id: str = Field(description="Chunk identifier")
    text: str = Field(description="Text segment of chunk")
    chunk_hash: str = Field(description="SHA-256 fingerprint of chunk text")
    start_line: int = Field(default=1, ge=1, description="1-based starting line")
    end_line: int = Field(default=1, ge=1, description="1-based ending line")
    token_estimate: int = Field(default=0, ge=0, description="Estimated token count")


class MigrationRunReport(BaseModel):
    """Comprehensive telemetry report produced following a migration run."""

    migration_id: str = Field(description="Unique execution run identifier")
    source_type: MigrationSourceType = Field(description="Migrated external platform")
    source_path: str = Field(description="Origin filesystem path or archive label")
    total_scanned: int = Field(ge=0, description="Total raw entries detected and scanned")
    total_admitted: int = Field(ge=0, description="Net new distinct entries admitted")
    total_skipped_duplicates: int = Field(
        ge=0, description="Redundant entries filtered by fingerprint deduplication"
    )
    total_chunks_generated: int = Field(
        ge=0, description="Total sliding window semantic chunks created"
    )
    vector_ingestion_status: str = Field(
        default="success", description="Status: success, skipped_no_provider, fallback_fts_only"
    )
    latency_ms: float = Field(ge=0.0, description="Total wall-clock duration in milliseconds")
    timestamp: float = Field(description="Epoch timestamp when migration completed")


# Alias for existing code consuming MigrationExecutionReport
class MigrationExecutionReport(MigrationRunReport):
    """Backward compatible report exposing total_imported."""

    @property
    def total_imported(self) -> int:
        return self.total_admitted

    @property
    def source_kind(self) -> MigrationSourceType:
        return self.source_type


class DetectedCompetitorArtifact(BaseModel):
    """Metadata describing a detected external competitor memory file or database."""

    source_kind: MigrationSourceType = Field(
        description="Identified ecosystem origin (e.g. hermes, openclaw)"
    )
    artifact_path: str = Field(description="Absolute local filesystem path to the asset")
    estimated_entries: int = Field(
        default=0, description="Estimated count of memories/facts contained"
    )
    detected_timestamp: float = Field(description="Epoch timestamp when detection occurred")
    summary: str = Field(description="Human-readable summary of detected cognitive contents")
