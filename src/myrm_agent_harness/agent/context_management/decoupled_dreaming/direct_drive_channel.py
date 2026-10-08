# [INPUT] MemoryDriveSpec, MemoryLogEntry, GoldenMemorySnapshot from .dreaming_types
# [OUTPUT] DirectMemoryDriveChannel
# [POS] Lightweight detached file/drive I/O channel operating directly on disk volumes without booting code sandboxes

"""Direct memory drive I/O channel operating without full sandbox initialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from .dreaming_types import (
    ConsolidatedEntityConcept,
    GoldenMemorySnapshot,
    MemoryDriveSpec,
    MemoryEntryRole,
    MemoryLogEntry,
)


class DirectMemoryDriveChannel:
    """Ultra-lightweight direct filesystem/database driver accessing persistent memory volumes."""

    @classmethod
    def initialize_drive_layout(cls, drive_spec: MemoryDriveSpec) -> Path:
        """Ensure base directory structure exists on the attached drive."""
        base_dir = Path(drive_spec.mount_path)
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "logs").mkdir(exist_ok=True)
        (base_dir / "snapshots").mkdir(exist_ok=True)
        return base_dir

    @classmethod
    def append_log_entries(
        cls,
        drive_spec: MemoryDriveSpec,
        entries: list[MemoryLogEntry],
    ) -> int:
        """Append raw interaction log entries to the drive's append-only jsonl log."""
        if drive_spec.read_only:
            raise PermissionError(f"Memory drive '{drive_spec.drive_id}' is mounted read-only")

        base_dir = cls.initialize_drive_layout(drive_spec)
        log_file = base_dir / "logs" / "memory_stream.jsonl"

        appended_count = 0
        with open(log_file, "a", encoding="utf-8") as f:
            for entry in entries:
                record: dict[str, object] = {
                    "entry_id": entry.entry_id,
                    "session_id": entry.session_id,
                    "timestamp_unix": entry.timestamp_unix,
                    "role": entry.role,
                    "content": entry.content,
                    "category": entry.category,
                    "importance_score": entry.importance_score,
                    "access_count": entry.access_count,
                    "tags": entry.tags,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                appended_count += 1

        return appended_count

    @classmethod
    def read_log_entries(
        cls,
        drive_spec: MemoryDriveSpec,
        since_timestamp: float = 0.0,
    ) -> list[MemoryLogEntry]:
        """Stream log entries from the attached memory drive filtered by timestamp."""
        base_dir = Path(drive_spec.mount_path)
        log_file = base_dir / "logs" / "memory_stream.jsonl"
        if not log_file.exists():
            return []

        entries: list[MemoryLogEntry] = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = cast(dict[str, object], json.loads(stripped))
                    ts = float(cast(int | float, raw.get("timestamp_unix", 0.0)))
                    if ts < since_timestamp:
                        continue

                    raw_tags = cast(list[object], raw.get("tags", []))
                    tags = [str(t) for t in raw_tags]

                    entry = MemoryLogEntry(
                        entry_id=str(raw.get("entry_id", "")),
                        session_id=str(raw.get("session_id", "")),
                        timestamp_unix=ts,
                        role=cast(MemoryEntryRole, raw.get("role", "user")),
                        content=str(raw.get("content", "")),
                        category=str(raw.get("category", "general")),
                        importance_score=float(
                            cast(int | float, raw.get("importance_score", 0.5))
                        ),
                        access_count=int(cast(int, raw.get("access_count", 0))),
                        tags=tags,
                    )
                    entries.append(entry)
                except Exception:
                    continue

        return entries

    @classmethod
    def save_golden_snapshot(
        cls,
        drive_spec: MemoryDriveSpec,
        snapshot: GoldenMemorySnapshot,
    ) -> Path:
        """Atomically persist golden memory snapshot into the drive."""
        if drive_spec.read_only:
            raise PermissionError(f"Memory drive '{drive_spec.drive_id}' is mounted read-only")

        base_dir = cls.initialize_drive_layout(drive_spec)
        snapshots_dir = base_dir / "snapshots"
        target_file = snapshots_dir / f"golden_v{snapshot.version}.json"
        tmp_file = snapshots_dir / f"golden_v{snapshot.version}.tmp"

        concepts_raw: list[dict[str, object]] = []
        for c in snapshot.concepts:
            concepts_raw.append({
                "concept_id": c.concept_id,
                "canonical_name": c.canonical_name,
                "aliases": c.aliases,
                "attributes": c.attributes,
                "confidence": c.confidence,
                "source_entry_ids": c.source_entry_ids,
                "last_reinforced_unix": c.last_reinforced_unix,
            })

        payload: dict[str, object] = {
            "snapshot_id": snapshot.snapshot_id,
            "version": snapshot.version,
            "timestamp_unix": snapshot.timestamp_unix,
            "drive_id": snapshot.drive_id,
            "checksum_sha256": snapshot.checksum_sha256,
            "total_entries_compacted": snapshot.total_entries_compacted,
            "concepts": concepts_raw,
        }

        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        # Atomic rename guarantees zero corruption
        tmp_file.replace(target_file)
        return target_file

    @classmethod
    def load_latest_snapshot(
        cls,
        drive_spec: MemoryDriveSpec,
    ) -> GoldenMemorySnapshot | None:
        """Retrieve and parse the most recent golden snapshot from disk."""
        base_dir = Path(drive_spec.mount_path)
        snapshots_dir = base_dir / "snapshots"
        if not snapshots_dir.exists():
            return None

        snapshot_files = sorted(
            snapshots_dir.glob("golden_v*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not snapshot_files:
            return None

        latest_path = snapshot_files[0]
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                raw = cast(dict[str, object], json.load(f))

            raw_concepts = cast(list[dict[str, object]], raw.get("concepts", []))
            concepts: list[ConsolidatedEntityConcept] = []
            for rc in raw_concepts:
                raw_aliases = cast(list[object], rc.get("aliases", []))
                raw_attrs = cast(dict[str, object], rc.get("attributes", {}))
                raw_sources = cast(list[object], rc.get("source_entry_ids", []))

                concepts.append(
                    ConsolidatedEntityConcept(
                        concept_id=str(rc.get("concept_id", "")),
                        canonical_name=str(rc.get("canonical_name", "")),
                        aliases=[str(a) for a in raw_aliases],
                        attributes={str(k): str(v) for k, v in raw_attrs.items()},
                        confidence=float(cast(int | float, rc.get("confidence", 0.8))),
                        source_entry_ids=[str(s) for s in raw_sources],
                        last_reinforced_unix=float(
                            cast(int | float, rc.get("last_reinforced_unix", 0.0))
                        ),
                    )
                )

            return GoldenMemorySnapshot(
                snapshot_id=str(raw.get("snapshot_id", "")),
                version=int(cast(int, raw.get("version", 1))),
                timestamp_unix=float(cast(int | float, raw.get("timestamp_unix", 0.0))),
                drive_id=str(raw.get("drive_id", drive_spec.drive_id)),
                concepts=concepts,
                checksum_sha256=str(raw.get("checksum_sha256", "")),
                total_entries_compacted=int(
                    cast(int, raw.get("total_entries_compacted", 0))
                ),
            )
        except Exception:
            return None
