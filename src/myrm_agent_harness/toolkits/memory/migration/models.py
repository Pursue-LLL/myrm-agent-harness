"""[POS]: src/myrm_agent_harness/toolkits/memory/migration/models.py
[INPUT]: None.
[OUTPUT]: Strongly-typed schemas for competitor memory detection, normalized translation, and migration auditing.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class CompetitorSourceKind(StrEnum):
    """Supported competitor and external memory asset ecosystems."""

    HERMES = "hermes"
    OPENCLAW = "openclaw"
    CHATGPT_EXPORT = "chatgpt_export"
    CLAUDE_PROJECT = "claude_project"
    GENERIC_JSON = "generic_json"


class DetectedCompetitorArtifact(BaseModel):
    """Metadata describing a detected external competitor memory file or database."""

    source_kind: CompetitorSourceKind = Field(
        description="Identified ecosystem origin (e.g. hermes, openclaw)."
    )
    artifact_path: str = Field(description="Absolute local filesystem path to the asset.")
    estimated_entries: int = Field(
        default=0, description="Estimated count of memories/facts contained."
    )
    detected_timestamp: float = Field(description="Epoch timestamp when detection occurred.")
    summary: str = Field(description="Human-readable summary of detected cognitive contents.")


class NormalizedMemoryPayload(BaseModel):
    """A single normalized cognitive memory unit translated from competitor schema."""

    source_kind: CompetitorSourceKind = Field(description="Original competitor ecosystem source.")
    source_id: str = Field(description="Original entry identifier or section reference.")
    raw_content: str = Field(description="Original unparsed text or serialization snippet.")
    normalized_content: str = Field(
        description="Cleansed, structured statement ready for ingestion."
    )
    layer_recommendation: str = Field(
        default="semantic",
        description="Recommended memory layer: profile, semantic, procedural, episodic.",
    )
    tags: list[str] = Field(
        default_factory=list, description="Extracted topic or categorical tags."
    )
    content_hash: str = Field(
        description="SHA-256 fingerprint for idempotent deduplication."
    )
    provenance_meta: dict[str, str] = Field(
        default_factory=dict, description="Audit provenance key-value pairs."
    )


class MigrationExecutionReport(BaseModel):
    """Audit report for an executed competitor memory migration run."""

    migration_id: str = Field(description="Unique migration execution identifier.")
    source_kind: CompetitorSourceKind = Field(description="Target competitor ecosystem migrated.")
    source_path: str = Field(description="Origin filesystem path ingested.")
    total_scanned: int = Field(description="Total entries parsed from raw artifact.")
    total_imported: int = Field(description="Net new entries successfully admitted.")
    total_skipped_duplicates: int = Field(
        description="Duplicates filtered out via content fingerprint hash."
    )
    imported_entries: list[NormalizedMemoryPayload] = Field(
        default_factory=list, description="Ingested normalized memory units."
    )
    timestamp: float = Field(description="Epoch timestamp when migration completed.")
