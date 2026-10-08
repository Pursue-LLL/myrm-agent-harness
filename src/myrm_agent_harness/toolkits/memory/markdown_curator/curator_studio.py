"""Core studio engine managing human-in-the-loop memory curation and Markdown bi-directional sync.

[INPUT]
- toolkits.memory.markdown_curator.bidi_sync_engine::MarkdownBidiSyncEngine (POS: Calculates bi-directional
  deltas between in-memory stores and Markdown mirrors.)
- toolkits.memory.markdown_curator.markdown_serializer::MarkdownMemorySerializer (POS: Serializes memory
  entries to human-friendly Markdown and parses them back.)
- toolkits.memory.markdown_curator.models::CuratedMemoryCategory, CuratedMemoryEntry, CuratedMemoryStatus,
  CuratorStudioSummary, MarkdownSyncDelta (POS: Types and models for markdown curator.)

[OUTPUT]
- MemoryCuratorStudio: Core studio engine managing human-in-the-loop memory curation and Markdown
  bi-directional sync.

[POS]
Core studio engine managing human-in-the-loop memory curation and Markdown bi-directional sync.
"""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.markdown_curator.bidi_sync_engine import (
    MarkdownBidiSyncEngine,
)
from myrm_agent_harness.toolkits.memory.markdown_curator.markdown_serializer import (
    MarkdownMemorySerializer,
)
from myrm_agent_harness.toolkits.memory.markdown_curator.models import (
    CuratedMemoryCategory,
    CuratedMemoryEntry,
    CuratedMemoryStatus,
    CuratorStudioSummary,
    MarkdownSyncDelta,
)


class MemoryCuratorStudio:
    """Core studio engine managing human-in-the-loop memory curation and Markdown bi-directional sync."""

    def __init__(
        self,
        serializer: MarkdownMemorySerializer | None = None,
        sync_engine: MarkdownBidiSyncEngine | None = None,
    ) -> None:
        self._serializer = serializer or MarkdownMemorySerializer()
        self._sync_engine = sync_engine or MarkdownBidiSyncEngine()
        self._entries: dict[str, CuratedMemoryEntry] = {}

    def add_entry(self, entry: CuratedMemoryEntry) -> CuratedMemoryEntry:
        """Register a memory entry into the studio, applying anti-misremembering confidence threshold."""
        # Anti-misremembering gate: If confidence < 0.8 and not already set, require human confirmation
        if entry.confidence < 0.8 and entry.status == CuratedMemoryStatus.CONFIRMED:
            entry.status = CuratedMemoryStatus.PENDING_CONFIRMATION

        self._entries[entry.entry_id] = entry
        return entry

    def get_entry(self, entry_id: str) -> CuratedMemoryEntry | None:
        """Retrieve an entry by its unique identifier."""
        return self._entries.get(entry_id)

    def update_entry(
        self,
        entry_id: str,
        title: str | None = None,
        content: str | None = None,
        category: CuratedMemoryCategory | None = None,
        status: CuratedMemoryStatus | None = None,
        tags: list[str] | None = None,
    ) -> CuratedMemoryEntry:
        """Update an existing curated memory entry and touch the updated_at timestamp."""
        entry = self._entries.get(entry_id)
        if not entry:
            raise KeyError(f"Memory entry '{entry_id}' not found.")

        if title is not None:
            entry.title = title
        if content is not None:
            entry.content = content
        if category is not None:
            entry.category = category
        if status is not None:
            entry.status = status
        if tags is not None:
            entry.tags = list(tags)

        entry.updated_at = datetime.now(UTC).isoformat()
        return entry

    def audit_entry(self, entry_id: str, is_approved: bool) -> CuratedMemoryEntry:
        """Human-in-the-loop audit gate: approve or reject pending memory entries."""
        entry = self._entries.get(entry_id)
        if not entry:
            raise KeyError(f"Memory entry '{entry_id}' not found.")

        entry.status = (
            CuratedMemoryStatus.CONFIRMED
            if is_approved
            else CuratedMemoryStatus.REJECTED
        )
        entry.updated_at = datetime.now(UTC).isoformat()
        return entry

    def erase_entry(self, entry_id: str, hard_erase: bool = True) -> bool:
        """One-click privacy wipe: purge or archive an entry permanently."""
        if entry_id not in self._entries:
            return False

        if hard_erase:
            self._entries.pop(entry_id, None)
        else:
            self._entries[entry_id].status = CuratedMemoryStatus.ARCHIVED
            self._entries[entry_id].updated_at = datetime.now(UTC).isoformat()
        return True

    def export_markdown(
        self,
        doc_title: str = "Workspace Memory Mirror",
        include_archived: bool = False,
    ) -> str:
        """Export active curated memory entries to formatted Markdown."""
        active_entries = [
            e
            for e in self._entries.values()
            if include_archived or e.status != CuratedMemoryStatus.ARCHIVED
        ]
        return self._serializer.serialize(active_entries, doc_title=doc_title)

    def sync_from_markdown(
        self,
        markdown_text: str,
        hard_delete: bool = False,
    ) -> MarkdownSyncDelta:
        """Parse workspace Markdown text and apply delta to the studio store."""
        parsed_entries = self._serializer.deserialize(markdown_text)
        return self._sync_engine.apply_sync(
            self._entries,
            parsed_entries,
            hard_delete=hard_delete,
        )

    def list_entries(
        self,
        category: CuratedMemoryCategory | None = None,
        status: CuratedMemoryStatus | None = None,
    ) -> list[CuratedMemoryEntry]:
        """List entries matching optional category and status criteria."""
        items: list[CuratedMemoryEntry] = []
        for entry in self._entries.values():
            if category and entry.category != category:
                continue
            if status and entry.status != status:
                continue
            items.append(entry)
        return sorted(items, key=lambda e: e.updated_at, reverse=True)

    def get_summary(self) -> CuratorStudioSummary:
        """Aggregate total count, confirmed/pending ratio, and category breakdown."""
        total = len(self._entries)
        confirmed = sum(
            1 for e in self._entries.values() if e.status == CuratedMemoryStatus.CONFIRMED
        )
        pending = sum(
            1
            for e in self._entries.values()
            if e.status == CuratedMemoryStatus.PENDING_CONFIRMATION
        )
        rejected = sum(
            1 for e in self._entries.values() if e.status == CuratedMemoryStatus.REJECTED
        )
        archived = sum(
            1 for e in self._entries.values() if e.status == CuratedMemoryStatus.ARCHIVED
        )

        categories_breakdown: dict[str, int] = {cat.value: 0 for cat in CuratedMemoryCategory}
        for e in self._entries.values():
            categories_breakdown[e.category.value] = (
                categories_breakdown.get(e.category.value, 0) + 1
            )

        return CuratorStudioSummary(
            total_entries=total,
            confirmed_count=confirmed,
            pending_count=pending,
            rejected_count=rejected,
            archived_count=archived,
            categories_breakdown=categories_breakdown,
        )
