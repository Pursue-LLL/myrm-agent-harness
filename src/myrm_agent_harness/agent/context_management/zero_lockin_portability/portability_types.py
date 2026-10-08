# [INPUT] None (Foundation domain types for zero-lockin portability)
# [OUTPUT] ExportPlatformType, NodeRole, ArchivedSessionNode, ArchivedSessionTree, MemoryFactCategory, ExtractedEntityFact, HydratedUserProfile, ZeroLockinArchiveManifest, UniversalArchivePayload, IngestionResultReport, PortabilityHealthBadge
# [POS] Domain data structures for universal context portability and cross-platform memory hydration

"""Type definitions for zero-lockin universal context portability and memory hydration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ExportPlatformType = Literal[
    "chatgpt",
    "claude_web",
    "instinct",
    "typingmind",
    "universal_myrm",
    "unknown",
]

NodeRole = Literal[
    "system",
    "user",
    "assistant",
    "tool",
]

MemoryFactCategory = Literal[
    "preference",
    "tech_stack",
    "project_context",
    "coding_style",
    "constraint",
    "domain_knowledge",
]

SovereigntyRating = Literal[
    "FULL_SOVEREIGNTY",
    "HIGH_PORTABILITY",
    "DEGRADED_PORTABILITY",
    "LOCKED_RISK",
]


@dataclass(frozen=True)
class ArchivedSessionNode:
    """A single normalized turn node within an archived conversational tree."""

    node_id: str
    parent_id: str | None
    children_ids: list[str] = field(default_factory=list)
    role: NodeRole = "user"
    content: str = ""
    thoughts: str | None = None
    model_name: str | None = None
    created_at_unix: float = 0.0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ArchivedSessionTree:
    """A complete session tree supporting branching, multiple turns, and metadata."""

    session_id: str
    title: str
    root_node_ids: list[str]
    nodes: dict[str, ArchivedSessionNode]
    created_at_iso: str
    updated_at_iso: str
    original_platform: ExportPlatformType = "unknown"
    tags: list[str] = field(default_factory=list)

    @property
    def total_messages(self) -> int:
        return len(self.nodes)


@dataclass(frozen=True)
class ExtractedEntityFact:
    """An atomic memory or profile fact extracted offline from historical conversation."""

    fact_id: str
    category: MemoryFactCategory
    subject: str
    predicate: str
    object_value: str
    confidence: float
    source_session_id: str
    context_snippet: str


@dataclass(frozen=True)
class HydratedUserProfile:
    """An aggregated user profile hydrated from ingested transcripts."""

    user_id: str
    preferred_languages: list[str] = field(default_factory=list)
    tech_stack_tags: list[str] = field(default_factory=list)
    coding_style_rules: list[str] = field(default_factory=list)
    high_frequency_topics: list[str] = field(default_factory=list)
    facts: list[ExtractedEntityFact] = field(default_factory=list)
    hydration_timestamp: float = 0.0

    @property
    def total_facts(self) -> int:
        return len(self.facts)


@dataclass(frozen=True)
class ZeroLockinArchiveManifest:
    """Manifest header guaranteeing zero-lockin portability and payload integrity."""

    version: str
    exported_platform: ExportPlatformType
    export_timestamp: float
    session_count: int
    message_count: int
    entity_fact_count: int
    checksum_sha256: str
    description: str = "Myrm Universal Zero-Lockin Context Archive"


@dataclass(frozen=True)
class UniversalArchivePayload:
    """Top-level archive packaging sessions, memory profile, and integrity manifest."""

    manifest: ZeroLockinArchiveManifest
    sessions: list[ArchivedSessionTree]
    user_profile: HydratedUserProfile | None = None


@dataclass(frozen=True)
class IngestionResultReport:
    """Summary report detailing the ingestion and normalization of an external archive."""

    source_platform: ExportPlatformType
    imported_sessions: int
    imported_messages: int
    extracted_facts: int
    parse_errors: list[str]
    processing_duration_ms: float
    success: bool


@dataclass(frozen=True)
class PortabilityHealthBadge:
    """Portability health score and sovereignty evaluation for UI and CLI."""

    portability_score: int
    sovereignty_rating: SovereigntyRating
    warnings: list[str]
    summary: str
