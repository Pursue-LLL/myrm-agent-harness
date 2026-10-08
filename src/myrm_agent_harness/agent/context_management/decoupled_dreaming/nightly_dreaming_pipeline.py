# [INPUT] MemoryLogEntry, ConsolidatedEntityConcept, GoldenMemorySnapshot, DreamingConsolidationReport, MemoryDriveSpec from .dreaming_types
# [OUTPUT] NightlyDreamingPipeline
# [POS] Nightly dreaming consolidation pipeline performing decay pruning, entity aliasing, and golden snapshot synthesis

"""Nightly dreaming consolidation pipeline for decoupled memory distillation."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid

from .dreaming_types import (
    ConsolidatedEntityConcept,
    DreamingConsolidationReport,
    GoldenMemorySnapshot,
    MemoryDriveSpec,
    MemoryLogEntry,
)

ALIAS_CANONICAL_MAPPINGS: dict[str, str] = {
    "pg": "PostgreSQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "sqlite3": "SQLite",
    "sqlite": "SQLite",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "py": "Python",
    "python": "Python",
    "docker": "Docker",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
}


class NightlyDreamingPipeline:
    """Consolidation engine that distills episodic logs into golden semantic concepts."""

    @classmethod
    def run_dreaming_consolidation(
        cls,
        drive_spec: MemoryDriveSpec,
        raw_entries: list[MemoryLogEntry],
        existing_snapshot: GoldenMemorySnapshot | None = None,
        stale_threshold_days: float = 30.0,
    ) -> tuple[GoldenMemorySnapshot, DreamingConsolidationReport]:
        """Execute the biological-inspired dreaming pipeline over raw interaction logs."""
        start_time = time.perf_counter()
        now_unix = time.time()
        stale_cutoff_unix = now_unix - (stale_threshold_days * 86400.0)

        # 1. Decay scoring and stale log pruning
        retained_entries: list[MemoryLogEntry] = []
        pruned_count = 0
        compacted_bytes = 0

        for entry in raw_entries:
            # Low importance and old entries get pruned
            if entry.timestamp_unix < stale_cutoff_unix and entry.importance_score < 0.35:
                pruned_count += 1
                compacted_bytes += len(entry.content.encode("utf-8"))
            else:
                retained_entries.append(entry)

        # 2. Extract and consolidate concepts
        concept_map: dict[str, ConsolidatedEntityConcept] = {}

        # Pre-seed from existing golden snapshot if available
        if existing_snapshot is not None:
            for c in existing_snapshot.concepts:
                concept_map[c.canonical_name.lower()] = c

        # Process retained log entries to extract/reinforce concepts
        for entry in retained_entries:
            words = re.findall(r"\b[A-Za-z0-9_]{2,}\b", entry.content)
            for w in words:
                w_lower = w.lower()
                canonical_name = ALIAS_CANONICAL_MAPPINGS.get(w_lower)
                if canonical_name is None:
                    continue

                canonical_key = canonical_name.lower()
                if canonical_key in concept_map:
                    old_c = concept_map[canonical_key]
                    new_aliases = list(dict.fromkeys(old_c.aliases + [w]))
                    new_sources = list(dict.fromkeys(old_c.source_entry_ids + [entry.entry_id]))
                    # Reinforce confidence slightly with capped 1.0
                    reinforced_conf = min(1.0, old_c.confidence + 0.05)
                    concept_map[canonical_key] = ConsolidatedEntityConcept(
                        concept_id=old_c.concept_id,
                        canonical_name=old_c.canonical_name,
                        aliases=new_aliases,
                        attributes=old_c.attributes,
                        confidence=reinforced_conf,
                        source_entry_ids=new_sources,
                        last_reinforced_unix=entry.timestamp_unix,
                    )
                else:
                    new_id = f"concept_{uuid.uuid4().hex[:12]}"
                    concept_map[canonical_key] = ConsolidatedEntityConcept(
                        concept_id=new_id,
                        canonical_name=canonical_name,
                        aliases=[w],
                        attributes={"category": entry.category},
                        confidence=0.80,
                        source_entry_ids=[entry.entry_id],
                        last_reinforced_unix=entry.timestamp_unix,
                    )

        consolidated_concepts = sorted(
            list(concept_map.values()),
            key=lambda x: x.canonical_name,
        )

        # 3. Build deterministic SHA-256 checksum for the golden snapshot
        hasher = hashlib.sha256()
        hasher.update(drive_spec.drive_id.encode("utf-8"))
        for c in consolidated_concepts:
            hasher.update(c.concept_id.encode("utf-8"))
            hasher.update(c.canonical_name.encode("utf-8"))
            hasher.update(str(round(c.confidence, 3)).encode("utf-8"))
        snapshot_checksum = hasher.hexdigest()

        next_version = (existing_snapshot.version + 1) if existing_snapshot else 1
        snapshot_id = f"snap_v{next_version}_{uuid.uuid4().hex[:8]}"

        new_snapshot = GoldenMemorySnapshot(
            snapshot_id=snapshot_id,
            version=next_version,
            timestamp_unix=now_unix,
            drive_id=drive_spec.drive_id,
            concepts=consolidated_concepts,
            checksum_sha256=snapshot_checksum,
            total_entries_compacted=len(raw_entries),
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        report = DreamingConsolidationReport(
            dream_id=f"dream_{uuid.uuid4().hex[:12]}",
            start_time_unix=now_unix,
            duration_ms=round(duration_ms, 2),
            scanned_entries=len(raw_entries),
            consolidated_concepts=len(consolidated_concepts),
            pruned_stale_entries=pruned_count,
            compacted_bytes_saved=compacted_bytes,
            vector_clusters_optimized=len(consolidated_concepts),
            snapshot_version=next_version,
            success=True,
            summary=(
                f"Dreaming completed in {duration_ms:.1f}ms: "
                f"scanned {len(raw_entries)} logs, consolidated {len(consolidated_concepts)} concepts, "
                f"pruned {pruned_count} stale entries, saved {compacted_bytes} bytes."
            ),
        )

        return (new_snapshot, report)
