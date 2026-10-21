"""Streaming archive writer.

[INPUT]
- state_archive.models (POS: manifest/entry value objects)
- state_archive.snapshot (POS: consistent SQLite capture)

[OUTPUT]
- ArchiveWriter: Context manager that streams files and SQLite snapshots into a
  zip with a trailing manifest, publishing atomically on success. A source it cannot
  open is skipped and recorded; a failure after a member began aborts the archive.
- SkippedEntry: A source that could not be archived, with the reason.

[POS]
Export half of ``infra/state_archive``. Peak memory is one copy buffer and peak
extra disk is one SQLite snapshot (created, zipped, deleted per database).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import tempfile
import time
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from .models import (
    MANIFEST_NAME,
    PAYLOAD_PREFIX,
    ArchiveEntry,
    ArchiveManifest,
    ArchiveWriteError,
    EntryKind,
)
from .snapshot import snapshot_sqlite

logger = logging.getLogger(__name__)

_COPY_BUFFER = 1 << 20
_ZIP_MIN_DATE = (1980, 1, 1, 0, 0, 0)
# Already-compressed payloads gain nothing from deflate and only burn CPU.
_STORED_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".avif",
        ".heic",
        ".mp3",
        ".m4a",
        ".aac",
        ".ogg",
        ".opus",
        ".flac",
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".zip",
        ".gz",
        ".bz2",
        ".xz",
        ".zst",
        ".7z",
        ".rar",
        ".pdf",
        ".woff",
        ".woff2",
    }
)


@dataclass(frozen=True, slots=True)
class SkippedEntry:
    """A source that was left out of the archive."""

    path: str
    reason: str


class ArchiveWriter:
    """Build one archive at ``dest``; the file only appears when ``finalize`` succeeds."""

    def __init__(
        self,
        dest: Path,
        *,
        producer: Mapping[str, str],
        metadata: Mapping[str, object] | None = None,
        work_dir: Path | None = None,
    ) -> None:
        self._dest = dest
        self._producer = dict(producer)
        self._metadata = dict(metadata or {})
        self._work_dir = work_dir or dest.parent
        self._partial = dest.with_name(dest.name + ".partial")
        self._zip: zipfile.ZipFile | None = None
        self._entries: list[ArchiveEntry] = []
        self._paths: set[str] = set()
        self._skipped: list[SkippedEntry] = []
        self._finalized = False

    @property
    def skipped(self) -> tuple[SkippedEntry, ...]:
        return tuple(self._skipped)

    def __enter__(self) -> ArchiveWriter:
        self._dest.parent.mkdir(parents=True, exist_ok=True)
        self._partial.unlink(missing_ok=True)
        self._zip = zipfile.ZipFile(
            self._partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None
        if not self._finalized:
            self._partial.unlink(missing_ok=True)

    def set_metadata(self, key: str, value: object) -> None:
        """Record a fact learned while capturing (e.g. by a ``prepare`` callback) in the manifest."""
        self._metadata[key] = value

    def skip(self, rel_path: str, reason: str) -> None:
        self._skipped.append(SkippedEntry(rel_path, reason))

    def add_file(self, src: Path, rel_path: str) -> ArchiveEntry | None:
        """Stream ``src`` into the archive; a file that cannot be opened is recorded as skipped.

        Raises ``ArchiveWriteError`` when reading or writing fails once the member has begun.
        """
        try:
            return self._write_member(src, rel_path, EntryKind.FILE)
        except OSError as exc:
            self.skip(rel_path, f"unreadable: {exc.__class__.__name__}")
            return None

    def add_sqlite(
        self,
        src: Path,
        rel_path: str,
        *,
        compact: bool = True,
        prepare: Callable[[Path], None] | None = None,
    ) -> ArchiveEntry | None:
        """Snapshot a live database, optionally let ``prepare`` rewrite the copy, then archive it.

        The temporary copy is always deleted, also on failure.
        """
        try:
            with tempfile.TemporaryDirectory(dir=self._work_dir, prefix=".snap-") as tmp:
                snap = Path(tmp) / "snapshot.sqlite"
                snapshot_sqlite(src, snap, compact=compact)
                if prepare is not None:
                    prepare(snap)
                return self._write_member(snap, rel_path, EntryKind.SQLITE, mtime=src.stat().st_mtime)
        except (OSError, ValueError, sqlite3.Error) as exc:
            logger.warning("[StateArchive] SQLite capture failed for %s: %s", rel_path, exc)
            self.skip(rel_path, f"snapshot failed: {exc.__class__.__name__}")
            return None

    def finalize(self) -> ArchiveManifest:
        """Write the manifest, close the zip, and atomically publish the archive."""
        if self._zip is None or self._finalized:
            raise RuntimeError("ArchiveWriter is not open")
        metadata = dict(self._metadata)
        metadata["skipped"] = [{"path": s.path, "reason": s.reason} for s in self._skipped]
        manifest = ArchiveManifest(
            created_at=datetime.now(UTC).isoformat(),
            producer=self._producer,
            entries=tuple(self._entries),
            metadata=metadata,
        )
        self._zip.writestr(MANIFEST_NAME, manifest.to_json())
        self._zip.close()
        self._zip = None
        os.replace(self._partial, self._dest)
        self._finalized = True
        return manifest

    def _write_member(
        self,
        src: Path,
        rel_path: str,
        kind: EntryKind,
        *,
        mtime: float | None = None,
    ) -> ArchiveEntry:
        if self._zip is None:
            raise RuntimeError("ArchiveWriter is not open")
        if rel_path in self._paths:
            raise ValueError(f"duplicate archive path: {rel_path}")
        stat = src.stat()
        info = zipfile.ZipInfo(PAYLOAD_PREFIX + rel_path, date_time=_zip_date(mtime or stat.st_mtime))
        info.compress_type = (
            zipfile.ZIP_STORED if Path(rel_path).suffix.lower() in _STORED_SUFFIXES else zipfile.ZIP_DEFLATED
        )
        digest = hashlib.sha256()
        size = 0
        with src.open("rb") as reader:
            # A zip cannot drop a member once it has begun, so a failure from here on leaves a member the manifest
            # will not declare and the reader rejects. It aborts the archive instead of being recorded as skipped.
            try:
                with self._zip.open(info, "w", force_zip64=True) as writer:
                    while chunk := reader.read(_COPY_BUFFER):
                        digest.update(chunk)
                        writer.write(chunk)
                        size += len(chunk)
            except OSError as exc:
                raise ArchiveWriteError(f"Writing {rel_path} failed part-way") from exc
        entry = ArchiveEntry(path=rel_path, kind=kind, size_bytes=size, sha256=digest.hexdigest())
        self._entries.append(entry)
        self._paths.add(rel_path)
        return entry


def _zip_date(timestamp: float) -> tuple[int, int, int, int, int, int]:
    parts = time.localtime(timestamp)[:6]
    return parts if parts >= _ZIP_MIN_DATE else _ZIP_MIN_DATE
