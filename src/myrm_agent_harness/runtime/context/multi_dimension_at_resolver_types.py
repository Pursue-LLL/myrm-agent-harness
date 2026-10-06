"""Data contracts and models for Unified Multi-Dimension At-Symbol Context Resolver."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AtReferenceKind(StrEnum):
    """Supported multi-dimensional resource categories referenced via @ notation."""

    FILE = "file"
    SESSION = "session"
    AGENT = "agent"
    DOC = "doc"
    ARTIFACT = "artifact"


class SnapshotDetailLevel(StrEnum):
    """Compression granularity of referenced contextual snapshots."""

    L0_SKELETON = "l0_skeleton"  # High-level overview (50-100 tokens)
    L1_STRUCTURED = "l1_structured"  # Structured bullet conclusions (200-500 tokens)
    FULL_PASS = "full_pass"  # Verbatim full content


@dataclass(frozen=True)
class ParsedAtReference:
    """Raw parsed symbol reference extracted from user prompt text."""

    raw_match: str
    kind: AtReferenceKind
    target_identifier: str
    start_index: int
    end_index: int


@dataclass(frozen=True)
class ResolvedAtResource:
    """Hydrated and compressed resource ready for prompt injection and UI citation."""

    kind: AtReferenceKind
    target_identifier: str
    title: str
    detail_level: SnapshotDetailLevel
    snippet: str
    token_estimate: int
    badge_label: str
    uri_or_path: str


@dataclass(frozen=True)
class AtContextIngestionResult:
    """Consolidated outcome of @-reference extraction, compression, and XML assembly."""

    cleaned_prompt: str
    references: tuple[ResolvedAtResource, ...]
    injected_context_xml: str
    total_tokens_consumed: int
