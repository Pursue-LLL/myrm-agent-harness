"""Bidirectional incremental synchronization engine between Markdown files and MemoryManager."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.file_sync.models import (
    FileMemoryEntry,
    FileMemorySyncReport,
    FileMemoryTopology,
)
from myrm_agent_harness.toolkits.memory.file_sync.store import FileMemoryStore

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class FileMemorySyncEngine:
    """Coordinates local-first markdown memory files with the MemoryManager backend."""

    def __init__(
        self,
        store: FileMemoryStore,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self._store = store
        self._memory_manager = memory_manager
        self._lock = asyncio.Lock()
        # Track last known (mtime, size_bytes) per relative file path
        self._known_stats: dict[str, tuple[float, int]] = {}
        # Track last known content SHA-256 hash per file
        self._known_file_hashes: dict[str, str] = {}
        # Track active parsed entry hashes
        self._indexed_entry_hashes: set[str] = set()

    @property
    def store(self) -> FileMemoryStore:
        """The bound file store."""
        return self._store

    @property
    def topology(self) -> FileMemoryTopology:
        """The topology of the file store."""
        return self._store.topology

    def bind_memory_manager(self, manager: MemoryManager) -> None:
        """Dynamically bind or update the active MemoryManager instance."""
        self._memory_manager = manager

    async def check_and_sync_on_ingress(self) -> FileMemorySyncReport:
        """Extremely lightweight freshness probe (<0.1ms if no files changed).

        Triggered before agent inference to guarantee latest edits are reflected.
        """
        async with self._lock:
            start_time = time.perf_counter()
            report = FileMemorySyncReport()

            # 1. Discover all candidate files
            candidate_paths: list[Path] = []
            main_path = self.topology.main_file_path
            if main_path.is_file():
                candidate_paths.append(main_path)

            daily_dir = self.topology.daily_dir_path
            if daily_dir.is_dir():
                candidate_paths.extend(daily_dir.glob("*.md"))

            # 2. Probe file stats to detect if any mtime/size drifted
            needs_resync = False
            for path in candidate_paths:
                rel_path = str(path.relative_to(self.topology.root_dir))
                stat = self._store.get_file_freshness(path)
                if stat is None:
                    continue

                known = self._known_stats.get(rel_path)
                if known != stat:
                    needs_resync = True
                    break

            # 3. Check for deleted files that were previously indexed
            current_rel_paths = {
                str(p.relative_to(self.topology.root_dir)) for p in candidate_paths
            }
            if set(self._known_stats.keys()) - current_rel_paths:
                needs_resync = True

            if not needs_resync:
                report.duration_ms = (time.perf_counter() - start_time) * 1000.0
                return report

            # 4. Perform incremental re-indexing
            return await self._execute_full_sync(candidate_paths, start_time)

    async def _execute_full_sync(
        self,
        candidate_paths: list[Path],
        start_time: float,
    ) -> FileMemorySyncReport:
        """Execute full differential sync from markdown files to memory backend."""
        report = FileMemorySyncReport()
        new_indexed_hashes: set[str] = set()

        for path in candidate_paths:
            rel_path = str(path.relative_to(self.topology.root_dir))
            stat = self._store.get_file_freshness(path)
            if stat is None:
                continue

            report.scanned_files.append(rel_path)
            self._known_stats[rel_path] = stat

            # Compute whole-file hash
            try:
                content = path.read_text(encoding="utf-8")
                file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            except OSError as e:
                report.errors.append(f"Failed to read {rel_path}: {e}")
                continue

            self._known_file_hashes[rel_path] = file_hash

            # Parse entries from file
            entries = self._store.read_entries(path)
            for entry in entries:
                new_indexed_hashes.add(entry.content_hash)
                if entry.content_hash not in self._indexed_entry_hashes:
                    # New or modified entry
                    report.added_count += 1
                    await self._ingest_entry_to_backend(entry)
                else:
                    report.unchanged_count += 1

        self._indexed_entry_hashes = new_indexed_hashes
        report.duration_ms = (time.perf_counter() - start_time) * 1000.0
        return report

    async def _ingest_entry_to_backend(self, entry: FileMemoryEntry) -> None:
        """Ingest a parsed file memory chunk into the bound MemoryManager."""
        if self._memory_manager is None:
            return

        try:
            tags = [f"file:{entry.source_file}", f"cat:{entry.category.value}"]
            if hasattr(self._memory_manager, "add_knowledge"):
                await self._memory_manager.add_knowledge(
                    content=entry.content,
                    tags=tags,
                )
            elif hasattr(self._memory_manager, "store"):
                from myrm_agent_harness.toolkits.memory.types import SemanticMemory

                memory = SemanticMemory(
                    user_id=getattr(self._memory_manager, "user_id", "default_user"),
                    content=entry.content,
                    tags=tags,
                    metadata={
                        "source_file": entry.source_file,
                        "line_start": str(entry.line_start),
                        "line_end": str(entry.line_end),
                        "anchor": entry.to_anchor(),
                        "file_hash": entry.content_hash,
                    },
                )
                await self._memory_manager.store(memory)
        except Exception as e:
            logger.warning(f"Failed to ingest file entry {entry.id} into MemoryManager: {e}")

    async def persist_episodic_note(
        self,
        text: str,
        title: str | None = None,
    ) -> FileMemoryEntry | None:
        """Atomically append an episodic note to daily memory and register it."""
        async with self._lock:
            entry = self._store.append_daily_note(text=text, title=title)
            if entry is not None:
                self._indexed_entry_hashes.add(entry.content_hash)
                await self._ingest_entry_to_backend(entry)
            return entry
