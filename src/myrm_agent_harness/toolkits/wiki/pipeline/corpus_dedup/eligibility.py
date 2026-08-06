"""Compile eligibility filter for wiki raw corpus paths.

[INPUT]
- core.structure::WikiStructure (POS: vault paths and raw listing)
- corpus_dedup.store::CorpusDedupStore (POS: dedup SQLite persistence)
- corpus_dedup.path_utils::normalize_raw_relative_path (POS: raw path key SSOT)

[OUTPUT]
- CorpusEligibilityFilter: blocked-path filtering for compile, queue, stale summary

[POS]
Compile eligibility gate. Excluded and trashed raw paths are omitted from compiler
input, queue enqueue, and stale detection. `compile_jobs_prevented` is incremented
only when the governor applies trash/exclude dispositions.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.path_utils import (
    normalize_raw_relative_path,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.store import (
    CorpusDedupStore,
)


class CorpusEligibilityFilter:
    """Filter raw paths excluded or trashed from compile and stale detection."""

    def __init__(self, structure: WikiStructure) -> None:
        self._structure = structure
        self._store = CorpusDedupStore(structure)

    @property
    def store(self) -> CorpusDedupStore:
        return self._store

    def blocked_paths(self) -> set[str]:
        return self._store.get_excluded_paths() | self._store.get_trashed_paths()

    def is_eligible_relative_path(self, relative_path: str) -> bool:
        normalized = normalize_raw_relative_path(relative_path)
        return normalized not in self.blocked_paths()

    def is_eligible_raw_file(self, raw_file: Path) -> bool:
        rel = raw_file.relative_to(self._structure.raw_dir).as_posix()
        return self.is_eligible_relative_path(rel)

    def filter_raw_paths(self, raw_files: list[Path]) -> list[Path]:
        blocked = self.blocked_paths()
        if not blocked:
            return raw_files
        kept: list[Path] = []
        for raw_file in raw_files:
            rel = raw_file.relative_to(self._structure.raw_dir).as_posix()
            if rel in blocked:
                continue
            kept.append(raw_file)
        return kept

    def filter_relative_paths(self, relative_paths: list[str]) -> list[str]:
        blocked = self.blocked_paths()
        if not blocked:
            return relative_paths
        kept: list[str] = []
        for relative_path in relative_paths:
            normalized = normalize_raw_relative_path(relative_path)
            if normalized in blocked:
                continue
            kept.append(normalized)
        return kept

    def count_eligible_raw_files(self) -> int:
        blocked = self.blocked_paths()
        count = 0
        for raw_file in self._structure.list_raw_files():
            rel = raw_file.relative_to(self._structure.raw_dir).as_posix()
            if rel not in blocked:
                count += 1
        return count
