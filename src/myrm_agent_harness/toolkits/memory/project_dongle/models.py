"""Domain models for Project Context USB Dongle and cross-agent relay protocol.

[INPUT]
- Workspace paths, bullet text content, block IDs, timestamps, and archive pointers.

[OUTPUT]
- DongleBlockType, DongleBlock, DongleArchivePointer, DongleState, SyncResult.

[POS]
- Core domain models for Item 152 ProjectContextUsbDongleAndCrossAgentRelaySuite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DongleBlockType(str, Enum):
    """Four-tier standard markdown memory block file types."""

    PROJECT_STATE = "PROJECT_STATE.md"
    DECISIONS = "DECISIONS.md"
    LESSONS = "LESSONS.md"
    INDEX = "INDEX.md"


@dataclass(frozen=True)
class DongleArchivePointer:
    """Pointer line left in primary file when an old block spills to archive."""

    block_id: str
    date_str: str
    summary: str
    target_archive_file: str

    def to_markdown(self) -> str:
        """Render standard pointer line."""
        return f"[archived {self.date_str} id:{self.block_id}] {self.summary} → {self.target_archive_file}"


@dataclass(frozen=True)
class DongleBlock:
    """Bullet block element in standard memory markdown files."""

    block_id: str
    block_type: DongleBlockType
    content: str
    created_date: str
    status: str = "active"
    tags: tuple[str, ...] = ()

    def to_markdown(self) -> str:
        """Render block as bullet item with block id and metadata."""
        tag_part = f" [{','.join(self.tags)}]" if self.tags else ""
        return f"- [BLK-{self.block_id}] [{self.created_date}]{tag_part} {self.content}"


@dataclass(frozen=True)
class DongleState:
    """Aggregated representation of the four-tier project memory dongle files."""

    workspace_dir: str
    project_state_blocks: tuple[DongleBlock, ...] = ()
    decision_blocks: tuple[DongleBlock, ...] = ()
    lesson_blocks: tuple[DongleBlock, ...] = ()
    index_content: str = ""
    archive_pointers: tuple[DongleArchivePointer, ...] = ()

    @property
    def total_active_blocks(self) -> int:
        """Total number of active blocks across all 3 tiers."""
        return len(self.project_state_blocks) + len(self.decision_blocks) + len(self.lesson_blocks)


@dataclass(frozen=True)
class SyncResult:
    """Result of incremental sync and optional archive spill operations."""

    updated_files: tuple[str, ...]
    added_blocks_count: int
    spilled_blocks_count: int
    created_pointers: tuple[DongleArchivePointer, ...] = ()
    message: str = ""
