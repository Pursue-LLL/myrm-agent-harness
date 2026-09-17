"""Physical file store and atomic operations for local-first memory files.

[INPUT]
- myrm_agent_harness.toolkits.memory.file_sync.models::FileMemoryTopology (POS: directory layout)
- myrm_agent_harness.toolkits.memory.file_sync.models::FileMemoryEntry (POS: structured memory chunk)
- myrm_agent_harness.toolkits.memory.file_sync.parser::LenientMarkdownParser (POS: tolerant parser)

[OUTPUT]
- FileMemoryStore: atomic file writer, reader, and freshness probe

[POS]
Physical I/O and atomicity guarantee layer for Markdown-backed memory storage.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.memory.file_sync.models import (
    FileMemoryEntry,
    FileMemoryTopology,
)
from myrm_agent_harness.toolkits.memory.file_sync.parser import LenientMarkdownParser

logger = logging.getLogger(__name__)


class FileMemoryStore:
    """Manages physical markdown files with atomic mutations and freshness checks."""

    def __init__(self, topology: FileMemoryTopology) -> None:
        self._topology = topology

    @property
    def topology(self) -> FileMemoryTopology:
        """The bound file topology."""
        return self._topology

    def ensure_topology(self) -> None:
        """Ensure all required memory directories exist."""
        try:
            self._topology.root_dir.mkdir(parents=True, exist_ok=True)
            self._topology.daily_dir_path.mkdir(parents=True, exist_ok=True)
            self._topology.archive_dir_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to initialize memory directory topology: {e}")
            raise

    def get_file_freshness(self, path: Path) -> tuple[float, int] | None:
        """Get (mtime, size_bytes) for a file via os.stat, or None if non-existent."""
        try:
            st = path.stat()
            return st.st_mtime, st.st_size
        except FileNotFoundError:
            return None
        except OSError as e:
            logger.warning(f"Error checking stat for {path}: {e}")
            return None

    def read_entries(self, path: Path) -> list[FileMemoryEntry]:
        """Read and parse structured entries from a given markdown file."""
        if not path.is_file():
            return []
        try:
            content = path.read_text(encoding="utf-8")
            relative_name = str(path.relative_to(self._topology.root_dir))
        except (OSError, ValueError) as e:
            logger.error(f"Failed to read memory file {path}: {e}")
            return []

        return LenientMarkdownParser.parse_document(
            content=content,
            source_filename=relative_name,
        )

    def read_all_workspace_entries(self) -> list[FileMemoryEntry]:
        """Discover and load all entries across MEMORY.md and daily notes."""
        all_entries: list[FileMemoryEntry] = []

        # 1. Main MEMORY.md
        main_file = self._topology.main_file_path
        if main_file.is_file():
            all_entries.extend(self.read_entries(main_file))

        # 2. Daily episodic notes
        daily_dir = self._topology.daily_dir_path
        if daily_dir.is_dir():
            for note_file in sorted(daily_dir.glob("*.md")):
                all_entries.extend(self.read_entries(note_file))

        return all_entries

    def write_atomic(self, target_path: Path, content: str) -> None:
        """Write content to target_path using an atomic temp-file replace strategy."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        dir_path = target_path.parent

        fd, temp_file_path = tempfile.mkstemp(
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            dir=str(dir_path),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file_path, target_path)
        except Exception as e:
            logger.error(f"Atomic write failed for {target_path}: {e}")
            try:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            except OSError:
                pass
            raise

    def append_daily_note(
        self,
        text: str,
        target_date: datetime | None = None,
        title: str | None = None,
    ) -> FileMemoryEntry | None:
        """Append an episodic note entry to the corresponding daily markdown log."""
        daily_path = self._topology.get_daily_file_path(target_date)
        dt = target_date or datetime.now(UTC)
        timestamp_str = dt.strftime("%H:%M:%S UTC")

        daily_path.parent.mkdir(parents=True, exist_ok=True)

        existing_content = ""
        if daily_path.is_file():
            try:
                existing_content = daily_path.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning(f"Could not read daily note {daily_path}: {e}")

        date_header = f"# Daily Memory: {dt.strftime('%Y-%m-%d')}\n\n"
        if not existing_content.strip():
            body = date_header
        else:
            body = existing_content.rstrip() + "\n\n"

        section_title = title or f"Note at {timestamp_str}"
        snippet = f"## {section_title}\n\n{text.strip()}\n"
        full_content = body + snippet

        self.write_atomic(daily_path, full_content)

        # Parse and return the newly created entry
        entries = self.read_entries(daily_path)
        return entries[-1] if entries else None
