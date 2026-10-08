"""Multi-tier deduplication and evolutionary conflict resolver.

[POS]
Defends vector storage from duplicate bloat through multi-tier fingerprinting:
file-level, content-hash level, and evolving source-id upsert tracking.

[INPUT]
- collections.abc.Sequence
- .models.ExtractedMemoryUnit

[OUTPUT]
- MigrationDeduplicator, DeduplicationResult
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from myrm_agent_harness.toolkits.memory.migration.models import ExtractedMemoryUnit


@dataclass
class DeduplicationResult:
    """Outcome of filtering duplicate items across migration runs."""

    admitted_units: list[ExtractedMemoryUnit] = field(default_factory=list)
    skipped_count: int = 0
    updated_count: int = 0


class MigrationDeduplicator:
    """Thread-safe multi-tier fingerprint ledger preventing duplicate ingestion."""

    def __init__(self) -> None:
        # File path -> (file_size, sha256_hash)
        self._seen_files: dict[str, tuple[int, str]] = {}
        # content_hash -> ExtractedMemoryUnit
        self._content_fingerprints: set[str] = set()
        # source_id -> content_hash (for version evolution tracking)
        self._source_version_map: dict[str, str] = {}

    def is_file_unchanged(self, file_path: Path | str) -> bool:
        """Level 1 Check: Verify whether file size and content hash are completely identical."""
        path = Path(file_path)
        if not path.is_file():
            return False

        path_key = str(path.resolve())
        stat = path.stat()
        if path_key in self._seen_files:
            cached_size, cached_hash = self._seen_files[path_key]
            if stat.st_size == cached_size:
                # Compute fast SHA-256 prefix
                curr_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                return curr_hash == cached_hash

        return False

    def record_file_seen(self, file_path: Path | str) -> None:
        """Record processed file metadata to enable Level 1 short-circuit on re-runs."""
        path = Path(file_path)
        if path.is_file():
            path_key = str(path.resolve())
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            self._seen_files[path_key] = (path.stat().st_size, file_hash)

    def filter_units(
        self, units: Sequence[ExtractedMemoryUnit]
    ) -> DeduplicationResult:
        """Filter incoming extracted memory units through Level 2 & 3 deduplication."""
        admitted: list[ExtractedMemoryUnit] = []
        skipped = 0
        updated = 0

        for unit in units:
            c_hash = unit.content_hash
            s_id = unit.source_id

            # Level 2: Exact content hash duplicate check
            if c_hash in self._content_fingerprints:
                skipped += 1
                continue

            # Level 3: Source ID evolution check (upsert semantic)
            if s_id in self._source_version_map:
                old_hash = self._source_version_map[s_id]
                # Same ID, new content: replace old fingerprint with updated version
                self._content_fingerprints.discard(old_hash)
                self._content_fingerprints.add(c_hash)
                self._source_version_map[s_id] = c_hash
                admitted.append(unit)
                updated += 1
                continue

            # Net new entry
            self._content_fingerprints.add(c_hash)
            self._source_version_map[s_id] = c_hash
            admitted.append(unit)

        return DeduplicationResult(
            admitted_units=admitted,
            skipped_count=skipped,
            updated_count=updated,
        )

    def reset(self) -> None:
        """Clear cached fingerprints."""
        self._seen_files.clear()
        self._content_fingerprints.clear()
        self._source_version_map.clear()
