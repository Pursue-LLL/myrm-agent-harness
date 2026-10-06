"""Strongly typed data contracts for Content-Addressed Session Dedup and CCR Context Archival.

Provides enums, chunk metadata, reference anchors, and transform results with zero Any.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DedupContentType(StrEnum):
    """Classification of content suitable for content-addressed dedup or CCR archival."""

    FILE_CONTENT = "file_content"  # Verbatim source files, configurations
    TOOL_OUTPUT = "tool_output"  # Long terminal logs, search returns, test outputs
    SYSTEM_RULE = "system_rule"  # Re-injected static instruction blocks
    ARBITRARY_CHUNK = "arbitrary_chunk"  # Large HTML, CSV, or document chunks


@dataclass(frozen=True)
class DedupConfig:
    """Threshold settings for session deduplication and CCR archival."""

    min_dedup_chars: int = 150
    max_inline_lines: int = 60
    preview_chars: int = 120
    content_ref_prefix: str = "[Content-Ref:"
    retrieve_marker_prefix: str = "[Retrieve-Marker:"


@dataclass(frozen=True)
class ArchivedChunkMetadata:
    """Metadata describing an archived large content chunk in the dedup vault."""

    marker_id: str
    content_hash: str
    content_type: DedupContentType
    source_hint: str
    byte_size: int
    line_count: int
    preview_summary: str
    archived_at_utc: str

    def format_marker_directive(self) -> str:
        """Render compact instruction for the agent to retrieve this chunk on demand."""
        return (
            f"[Retrieve-Marker: marker_id={self.marker_id} | "
            f"source={self.source_hint} | lines={self.line_count} | bytes={self.byte_size} | "
            f"preview=\"{self.preview_summary}\" | "
            f"use retrieve_artifact(\"{self.marker_id}\") to expand]"
        )


@dataclass(frozen=True)
class ContentRefAnchor:
    """Deterministic reference pointer for identical content repeated across turns."""

    content_hash: str
    source_hint: str
    line_count: int
    first_seen_turn: int

    def format_ref_directive(self) -> str:
        """Render deterministic placeholder for identical repeated content."""
        short_hash = self.content_hash[:12]
        return (
            f"[Content-Ref: sha256:{short_hash} | {self.source_hint} | "
            f"{self.line_count} lines | unchanged since turn {self.first_seen_turn}]"
        )


@dataclass(frozen=True)
class CCRTransformResult:
    """Outcome of scanning and transforming a context payload."""

    transformed_content: str
    archived_count: int
    deduped_count: int
    original_chars: int
    compressed_chars: int
    reduction_ratio: float
    markers_created: tuple[ArchivedChunkMetadata, ...] = field(default_factory=tuple)
    refs_created: tuple[ContentRefAnchor, ...] = field(default_factory=tuple)
