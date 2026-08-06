"""Scan wiki raw corpus for duplicate groups.

[POS]
See module docstring.
"""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.fingerprint import (
    build_fingerprint,
    is_near_duplicate,
    recommend_keep_path,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.store import (
    CorpusDedupStore,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.types import (
    DedupTier,
    DuplicateMember,
    GroupStatus,
    RawFileFingerprint,
    ScanProgress,
    ScanResult,
)


class CorpusDedupScanner:
    """Scan eligible raw files and persist duplicate groups."""

    def __init__(self, structure: WikiStructure) -> None:
        self._structure = structure
        self._store = CorpusDedupStore(structure)
        from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.eligibility import (
            CorpusEligibilityFilter,
        )

        self._eligibility = CorpusEligibilityFilter(structure)

    @property
    def store(self) -> CorpusDedupStore:
        return self._store

    def scan(self, *, incremental: bool = False) -> ScanResult:
        start = time.perf_counter()
        raw_files = self._eligibility.filter_raw_paths(self._structure.list_raw_files())
        total = len(raw_files)
        active_paths: set[str] = set()
        fingerprints: list[RawFileFingerprint] = []
        files_recomputed = 0

        self._store.set_scan_progress(
            ScanProgress(
                phase="scanning",
                files_scanned=0,
                files_total=total,
                message="Scanning raw corpus",
            )
        )

        for index, raw_file in enumerate(raw_files, start=1):
            try:
                rel = raw_file.relative_to(self._structure.raw_dir).as_posix()
                active_paths.add(rel)
                fingerprint, recomputed = self._resolve_fingerprint(
                    raw_file, rel, incremental=incremental
                )
                fingerprints.append(fingerprint)
                if recomputed:
                    files_recomputed += 1
            except OSError:
                continue
            if index % 25 == 0 or index == total:
                self._store.set_scan_progress(
                    ScanProgress(
                        phase="scanning",
                        files_scanned=index,
                        files_total=total,
                        message="Scanning raw corpus",
                    )
                )

        removed_cache = self._store.prune_file_fingerprints(active_paths)
        if incremental and files_recomputed == 0 and removed_cache == 0:
            open_groups = len(self._store.list_groups(status=GroupStatus.OPEN))
            duration_ms = int((time.perf_counter() - start) * 1000)
            self._store.mark_scan_complete()
            self._store.set_scan_progress(
                ScanProgress(
                    phase="done",
                    files_scanned=total,
                    files_total=total,
                    groups_found=open_groups,
                    message="Scan complete (incremental cache hit)",
                )
            )
            return ScanResult(
                files_scanned=total,
                groups_found=open_groups,
                open_groups=open_groups,
                exact_groups=0,
                normalized_groups=0,
                near_groups=0,
                duration_ms=duration_ms,
                incremental=True,
            )

        self._store.set_scan_progress(
            ScanProgress(
                phase="grouping",
                files_scanned=total,
                files_total=total,
                message="Grouping duplicates",
            )
        )
        deferred_member_sets = self._store.collect_deferred_member_sets()
        self._store.clear_scan_groups()
        grouped_paths: set[str] = set()
        exact_groups, exact_paths = self._group_by_key(
            fingerprints,
            key=lambda item: item.exact_hash,
            tier=DedupTier.EXACT,
            deferred_member_sets=deferred_member_sets,
        )
        grouped_paths.update(exact_paths)
        normalized_remaining = [
            item for item in fingerprints if item.relative_path not in grouped_paths
        ]
        normalized_groups, normalized_paths = self._group_by_key(
            normalized_remaining,
            key=lambda item: item.normalized_hash,
            tier=DedupTier.NORMALIZED,
            deferred_member_sets=deferred_member_sets,
        )
        grouped_paths.update(normalized_paths)
        near_remaining = [
            item for item in fingerprints if item.relative_path not in grouped_paths
        ]
        near_groups, near_paths = self._group_near(
            near_remaining, deferred_member_sets=deferred_member_sets
        )
        grouped_paths.update(near_paths)

        groups_found = exact_groups + normalized_groups + near_groups
        self._store.mark_scan_complete()
        self._store.set_scan_progress(
            ScanProgress(
                phase="done",
                files_scanned=total,
                files_total=total,
                groups_found=groups_found,
                message="Scan complete",
            )
        )
        duration_ms = int((time.perf_counter() - start) * 1000)
        open_groups = len(self._store.list_groups(status=GroupStatus.OPEN))
        return ScanResult(
            files_scanned=total,
            groups_found=groups_found,
            open_groups=open_groups,
            exact_groups=exact_groups,
            normalized_groups=normalized_groups,
            near_groups=near_groups,
            duration_ms=duration_ms,
            incremental=incremental,
        )

    def _resolve_fingerprint(
        self,
        raw_file: Path,
        relative_path: str,
        *,
        incremental: bool,
    ) -> tuple[RawFileFingerprint, bool]:
        stat = raw_file.stat()
        if incremental:
            cached = self._store.get_cached_fingerprint(relative_path)
            if (
                cached is not None
                and cached.size_bytes == stat.st_size
                and cached.mtime_ns == stat.st_mtime_ns
            ):
                return cached, False
        fingerprint = build_fingerprint(raw_file, relative_path=relative_path)
        self._store.upsert_file_fingerprint(fingerprint)
        return fingerprint, True

    def _group_by_key(
        self,
        fingerprints: list[RawFileFingerprint],
        *,
        key,
        tier: DedupTier,
        deferred_member_sets: set[frozenset[str]],
    ) -> tuple[int, set[str]]:
        buckets: dict[str, list[RawFileFingerprint]] = defaultdict(list)
        for item in fingerprints:
            buckets[key(item)].append(item)
        created = 0
        grouped_paths: set[str] = set()
        for bucket_key, members in buckets.items():
            if len(members) < 2:
                continue
            if self._should_skip_group(members):
                continue
            keep_path = recommend_keep_path(members)
            group_members = [
                DuplicateMember(
                    relative_path=member.relative_path,
                    size_bytes=member.size_bytes,
                    mtime_ns=member.mtime_ns,
                )
                for member in members
            ]
            self._store.save_group(
                tier=tier,
                fingerprint=bucket_key,
                recommended_keep_path=keep_path,
                members=group_members,
                status=self._resolve_group_status(members, deferred_member_sets),
            )
            created += 1
            grouped_paths.update(member.relative_path for member in members)
        return created, grouped_paths

    def _group_near(
        self,
        fingerprints: list[RawFileFingerprint],
        *,
        deferred_member_sets: set[frozenset[str]],
    ) -> tuple[int, set[str]]:
        if len(fingerprints) < 2:
            return 0, set()
        assigned: set[str] = set()
        grouped_paths: set[str] = set()
        created = 0
        ordered = sorted(fingerprints, key=lambda item: item.relative_path)
        for index, anchor in enumerate(ordered):
            if anchor.relative_path in assigned:
                continue
            cluster = [anchor]
            for candidate in ordered[index + 1 :]:
                if candidate.relative_path in assigned:
                    continue
                if is_near_duplicate(anchor.simhash, candidate.simhash):
                    cluster.append(candidate)
            if len(cluster) < 2:
                continue
            if self._should_skip_group(cluster):
                continue
            keep_path = recommend_keep_path(cluster)
            group_members = [
                DuplicateMember(
                    relative_path=member.relative_path,
                    size_bytes=member.size_bytes,
                    mtime_ns=member.mtime_ns,
                )
                for member in cluster
            ]
            fingerprint = f"near:{anchor.simhash:x}"
            self._store.save_group(
                tier=DedupTier.NEAR,
                fingerprint=fingerprint,
                recommended_keep_path=keep_path,
                members=group_members,
                status=self._resolve_group_status(cluster, deferred_member_sets),
            )
            for member in cluster:
                assigned.add(member.relative_path)
                grouped_paths.add(member.relative_path)
            created += 1
        return created, grouped_paths

    def _should_skip_group(self, members: list[RawFileFingerprint]) -> bool:
        paths = [member.relative_path for member in members]
        if len(paths) < 2:
            return False
        for left_index, left in enumerate(paths):
            for right in paths[left_index + 1 :]:
                if not self._store.is_pair_dismissed(left, right):
                    return False
        return True

    def _resolve_group_status(
        self,
        members: list[RawFileFingerprint],
        deferred_member_sets: set[frozenset[str]],
    ) -> GroupStatus:
        member_paths = frozenset(member.relative_path for member in members)
        if self._matches_deferred_cluster(member_paths, deferred_member_sets):
            return GroupStatus.DEFERRED
        return GroupStatus.OPEN

    @staticmethod
    def _matches_deferred_cluster(
        member_paths: frozenset[str],
        deferred_member_sets: set[frozenset[str]],
    ) -> bool:
        """Keep deferred status when a rescan regroups or grows the same duplicate cluster."""
        if len(member_paths) < 2:
            return False
        for deferred_paths in deferred_member_sets:
            if len(deferred_paths) < 2:
                continue
            overlap = deferred_paths & member_paths
            if len(overlap) < 2:
                continue
            if deferred_paths <= member_paths or member_paths <= deferred_paths:
                return True
        return False
