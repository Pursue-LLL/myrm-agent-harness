"""State archive primitive: consistent snapshots, verified archives, journaled promotion.

[INPUT]
- state_archive.models / snapshot / writer / reader / promotion

[OUTPUT]
- Public facade: ArchiveWriter, ArchiveWriteError, read_manifest, extract_payload, ensure_free_space,
  snapshot_sqlite, is_sqlite_file, promote, recover_interrupted, plus the value objects.

[POS]
Generic mechanism layer for instance export/import and restore points. Knows nothing about
which application paths exist or how they are classified; that policy belongs to the caller.
"""

from .models import (
    ARCHIVE_FORMAT,
    ARCHIVE_FORMAT_VERSION,
    ArchiveEntry,
    ArchiveErrorCode,
    ArchiveLimits,
    ArchiveManifest,
    ArchiveVerificationError,
    ArchiveWriteError,
    EntryKind,
    InsufficientSpaceError,
)
from .promotion import (
    PromotionJournal,
    PromotionPhase,
    PromotionPlan,
    promote,
    recover_interrupted,
    rollback,
)
from .reader import ensure_free_space, extract_payload, read_manifest
from .snapshot import is_sqlite_file, snapshot_sqlite
from .writer import ArchiveWriter, SkippedEntry

__all__ = [
    "ARCHIVE_FORMAT",
    "ARCHIVE_FORMAT_VERSION",
    "ArchiveEntry",
    "ArchiveErrorCode",
    "ArchiveLimits",
    "ArchiveManifest",
    "ArchiveVerificationError",
    "ArchiveWriteError",
    "ArchiveWriter",
    "EntryKind",
    "InsufficientSpaceError",
    "PromotionJournal",
    "PromotionPhase",
    "PromotionPlan",
    "SkippedEntry",
    "ensure_free_space",
    "extract_payload",
    "is_sqlite_file",
    "promote",
    "read_manifest",
    "recover_interrupted",
    "rollback",
    "snapshot_sqlite",
]
