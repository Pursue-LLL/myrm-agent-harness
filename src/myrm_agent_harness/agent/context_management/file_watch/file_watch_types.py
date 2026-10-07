"""Types and models for file watch.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- FileMutationKind: Classification of external workspace file mutation event.
- DocumentFreshnessStatus: Freshness status of workspace document bound inside session context.
- FileFingerprint: Deterministic hash fingerprint and metadata of a workspace file.
- SessionDocumentBinding: Document cache entry bound to a specific chat session.
- ContextInvalidationNudge: Lightweight ambient notification indicating external file edit occurred.
- AutoIngressResult: Report generated upon incremental re-ingestion of a stale document.

[POS]
Types and models for file watch.
"""

# ============================================================================
# Workspace File Watch Context Invalidation & Auto-Ingress Contracts (Item 165)
# Strong typing contracts for local workspace file watch, session document cache
# fingerprint binding, passive invalidation, ambient nudges, and auto-ingress.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class FileMutationKind(str, Enum):
    """Classification of external workspace file mutation event."""

    MODIFIED = "modified"
    CREATED = "created"
    DELETED = "deleted"


class DocumentFreshnessStatus(str, Enum):
    """Freshness status of workspace document bound inside session context."""

    FRESH = "fresh"
    STALE = "stale"
    RE_INDEXED = "re_indexed"
    EVICTED = "evicted"


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    """Deterministic hash fingerprint and metadata of a workspace file."""

    path: str
    sha256: str
    mtime_ns: int
    byte_size: int


@dataclass(frozen=True, slots=True)
class SessionDocumentBinding:
    """Document cache entry bound to a specific chat session."""

    session_id: str
    path: str
    fingerprint: FileFingerprint
    cached_content: str
    status: DocumentFreshnessStatus
    cached_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class ContextInvalidationNudge:
    """Lightweight ambient notification indicating external file edit occurred."""

    session_id: str
    path: str
    mutation_kind: FileMutationKind
    old_sha256: str
    new_sha256: str
    nudge_message: str
    timestamp_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class AutoIngressResult:
    """Report generated upon incremental re-ingestion of a stale document."""

    session_id: str
    path: str
    previous_sha256: str
    updated_sha256: str
    byte_delta: int
    refreshed_at_iso: str
    status: DocumentFreshnessStatus
