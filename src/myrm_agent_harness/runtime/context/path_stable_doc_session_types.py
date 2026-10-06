"""Type definitions for File-Path SHA-256 Stable Document Session Binding Hub.

Defines contracts for deterministic session derivation, cross-turn diff proposals,
cached parsed document slices, and multi-document isolation barriers.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DocSessionBindingInfo:
    """Metadata describing a deterministic document session binding."""

    file_path: str
    canonical_path: str
    session_id: str
    doc_basename: str
    created_at: float
    last_accessed_at: float


@dataclass(frozen=True)
class DocDiffProposalEntry:
    """Represents a patch or diff proposal suggested for a document turn."""

    proposal_id: str
    turn_index: int
    target_section: str
    summary: str
    is_applied: bool
    is_rejected: bool
    created_at: float


@dataclass(frozen=True)
class DocChunkCacheEntry:
    """Represents a cached parsed chunk or slice of a document."""

    chunk_id: str
    section_title: str
    content_snippet: str
    token_estimate: int
    checksum: str


@dataclass(frozen=True)
class DocSessionContinuityContext:
    """Aggregated continuity context synthesized for cross-turn ReAct loops."""

    session_id: str
    canonical_path: str
    total_proposals: int
    applied_proposals: int
    cached_chunks_count: int
    context_summary_xml: str
    active_proposal_ids: tuple[str, ...] = field(default_factory=tuple)
