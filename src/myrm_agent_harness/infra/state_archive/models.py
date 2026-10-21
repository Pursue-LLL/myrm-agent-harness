"""Data models, limits, and errors for the state archive primitive.

[INPUT]
- (stdlib only)

[OUTPUT]
- ArchiveEntry / ArchiveManifest: Self-describing archive content index (JSON round-trippable).
- ArchiveLimits: Upper bounds enforced while reading untrusted archives.
- ArchiveErrorCode / ArchiveVerificationError / ArchiveWriteError / InsufficientSpaceError: Typed failures.
- Format constants shared by writer and reader.

[POS]
Framework-neutral value objects of ``infra/state_archive``. Nothing here knows
which application paths exist; callers decide what is archived.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

ARCHIVE_FORMAT = "myrm-state-archive"
ARCHIVE_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
PAYLOAD_PREFIX = "payload/"

DEFAULT_MAX_ENTRIES = 500_000
DEFAULT_MAX_MANIFEST_BYTES = 64 * 1024 * 1024


class EntryKind(StrEnum):
    """How an entry was captured."""

    FILE = "file"
    SQLITE = "sqlite"


class ArchiveErrorCode(StrEnum):
    """Machine-readable reason an archive was rejected."""

    NOT_A_ZIP = "not_a_zip"
    MISSING_MANIFEST = "missing_manifest"
    BAD_MANIFEST = "bad_manifest"
    UNSUPPORTED_FORMAT = "unsupported_format"
    TOO_MANY_ENTRIES = "too_many_entries"
    TOO_LARGE = "too_large"
    UNSAFE_PATH = "unsafe_path"
    SYMLINK = "symlink"
    DUPLICATE_ENTRY = "duplicate_entry"
    CONTENT_MISMATCH = "content_mismatch"
    SIZE_MISMATCH = "size_mismatch"
    HASH_MISMATCH = "hash_mismatch"


class ArchiveVerificationError(Exception):
    """Raised when an archive violates structural, safety, or integrity rules."""

    def __init__(self, code: ArchiveErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ArchiveWriteError(RuntimeError):
    """Raised when writing a member fails after it began, which leaves the archive unfit to publish."""


class InsufficientSpaceError(OSError):
    """Raised when the target volume cannot hold the required bytes."""

    def __init__(self, required_bytes: int, free_bytes: int) -> None:
        super().__init__(f"Insufficient disk space: need {required_bytes} bytes, {free_bytes} free")
        self.required_bytes = required_bytes
        self.free_bytes = free_bytes


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    """One payload member of an archive."""

    path: str
    kind: EntryKind
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Bounds applied before any payload byte is extracted."""

    max_entries: int = DEFAULT_MAX_ENTRIES
    max_total_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class ArchiveManifest:
    """Content index stored as the last member of every archive."""

    created_at: str
    producer: Mapping[str, str]
    entries: tuple[ArchiveEntry, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)
    format: str = ARCHIVE_FORMAT
    format_version: int = ARCHIVE_FORMAT_VERSION

    @property
    def total_bytes(self) -> int:
        return sum(entry.size_bytes for entry in self.entries)

    def to_json(self) -> str:
        return json.dumps(
            {
                "format": self.format,
                "format_version": self.format_version,
                "created_at": self.created_at,
                "producer": dict(self.producer),
                "metadata": dict(self.metadata),
                "entries": [
                    {"path": e.path, "kind": e.kind.value, "size_bytes": e.size_bytes, "sha256": e.sha256}
                    for e in self.entries
                ],
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> ArchiveManifest:
        try:
            data = json.loads(raw)
            entries = tuple(
                ArchiveEntry(
                    path=str(item["path"]),
                    kind=EntryKind(item["kind"]),
                    size_bytes=_non_negative_int(item["size_bytes"]),
                    sha256=str(item["sha256"]),
                )
                for item in data["entries"]
            )
            return cls(
                format=str(data["format"]),
                format_version=int(data["format_version"]),
                created_at=str(data["created_at"]),
                producer={str(k): str(v) for k, v in dict(data["producer"]).items()},
                metadata=dict(data.get("metadata", {})),
                entries=entries,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ArchiveVerificationError(ArchiveErrorCode.BAD_MANIFEST, f"Malformed manifest: {exc}") from exc


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("size must be a non-negative integer")
    return value
