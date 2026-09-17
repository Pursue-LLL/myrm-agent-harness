"""Data models for File-as-Memory Local-First synchronization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class FileMemoryCategory(StrEnum):
    """Category of file-based memory entry."""

    RULE = "rule"
    PREFERENCE = "preference"
    PROFILE = "profile"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"
    GENERAL = "general"


@dataclass(frozen=True, slots=True)
class FileMemoryEntry:
    """A structured memory chunk parsed from a Markdown document."""

    id: str
    content: str
    source_file: str
    line_start: int
    line_end: int
    category: FileMemoryCategory = FileMemoryCategory.GENERAL
    title: str = ""
    content_hash: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def to_anchor(self) -> str:
        """Format entry as human-readable source anchor tag."""
        if self.line_start == self.line_end:
            return f"[source: {self.source_file}#L{self.line_start}]"
        return f"[source: {self.source_file}#L{self.line_start}-L{self.line_end}]"


@dataclass(frozen=True, slots=True)
class FileMemoryTopology:
    """Directory and file topology definition for local-first memory."""

    root_dir: Path
    main_memory_file: str = "MEMORY.md"
    daily_dirname: str = "memory/daily"
    archive_dirname: str = "memory/archive"

    @property
    def main_file_path(self) -> Path:
        """Absolute path to the primary MEMORY.md file."""
        return self.root_dir / self.main_memory_file

    @property
    def daily_dir_path(self) -> Path:
        """Absolute path to the episodic daily notes directory."""
        return self.root_dir / self.daily_dirname

    @property
    def archive_dir_path(self) -> Path:
        """Absolute path to the historical archive directory."""
        return self.root_dir / self.archive_dirname

    def get_daily_file_path(self, target_date: datetime | None = None) -> Path:
        """Get absolute path to a specific daily memory Markdown file."""
        dt = target_date or datetime.now(UTC)
        date_str = dt.strftime("%Y-%m-%d")
        return self.daily_dir_path / f"{date_str}.md"


@dataclass(slots=True)
class FileMemorySyncReport:
    """Summary report detailing the outcome of a sync cycle."""

    added_count: int = 0
    updated_count: int = 0
    deleted_count: int = 0
    unchanged_count: int = 0
    scanned_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def has_changes(self) -> bool:
        """Return True if any mutating synchronization action was taken."""
        return (self.added_count + self.updated_count + self.deleted_count) > 0
