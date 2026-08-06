"""Types for raw corpus deduplication governance.

[POS]
See module docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class DedupTier(StrEnum):
    """Duplicate detection tier."""

    EXACT = "exact"
    NORMALIZED = "normalized"
    NEAR = "near"


class DispositionAction(StrEnum):
    """User disposition for a duplicate group."""

    TRASH = "trash"
    EXCLUDE = "exclude"
    DISMISS = "dismiss"
    DEFER = "defer"


class GroupStatus(StrEnum):
    """Review status for a duplicate group."""

    OPEN = "open"
    DEFERRED = "deferred"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class RawFileFingerprint:
    """Fingerprints collected for one raw file."""

    relative_path: str
    exact_hash: str
    normalized_hash: str
    simhash: int
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class DuplicateMember:
    """One member of a duplicate group."""

    relative_path: str
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class DuplicateMemberSnippet:
    """Comparable body snippet for duplicate review."""

    relative_path: str
    snippet: str


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """A cluster of potentially duplicate raw files."""

    group_id: int
    tier: DedupTier
    fingerprint: str
    recommended_keep_path: str
    status: GroupStatus
    members: tuple[DuplicateMember, ...]


@dataclass(frozen=True, slots=True)
class ScanProgress:
    """Incremental scan progress snapshot."""

    phase: Literal["idle", "scanning", "grouping", "done", "failed"] = "idle"
    files_scanned: int = 0
    files_total: int = 0
    groups_found: int = 0
    message: str = ""


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Outcome of a corpus dedup scan."""

    files_scanned: int
    groups_found: int
    open_groups: int
    exact_groups: int
    normalized_groups: int
    near_groups: int
    duration_ms: int
    incremental: bool = False


@dataclass(frozen=True, slots=True)
class DispositionResult:
    """Outcome of applying a disposition to one group."""

    group_id: int
    action: DispositionAction
    affected_paths: tuple[str, ...] = field(default_factory=tuple)
    compile_jobs_prevented: int = 0


@dataclass(frozen=True, slots=True)
class DedupStats:
    """Overview stats for Settings / API."""

    duplicate_groups_pending: int
    compile_jobs_prevented: int
    eligible_raw_count: int
    excluded_raw_count: int
    trashed_raw_count: int


@dataclass(frozen=True, slots=True)
class TrashedRawEntry:
    """One raw file moved to corpus trash."""

    relative_path: str
    trash_relpath: str
    content_hash: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ExcludedRawEntry:
    """One raw file excluded from compile via dedup disposition."""

    relative_path: str
    reason: str
    created_at: str


@dataclass(frozen=True, slots=True)
class VaultHygieneSnapshot:
    """Trashed and excluded raw paths for Settings review."""

    trashed: tuple[TrashedRawEntry, ...]
    excluded: tuple[ExcludedRawEntry, ...]
