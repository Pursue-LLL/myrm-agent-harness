# [POS]: src/myrm_agent_harness/toolkits/memory/markdown_curator/bidi_sync_engine.py
# [INPUT]: src.myrm_agent_harness.toolkits.memory.markdown_curator.models
# [OUTPUT]: MarkdownBidiSyncEngine

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.markdown_curator.models import (
    CuratedMemoryEntry,
    CuratedMemoryStatus,
    MarkdownSyncDelta,
)


class MarkdownBidiSyncEngine:
    """Calculates bi-directional deltas between in-memory stores and Markdown mirrors."""

    def compute_delta(
        self,
        in_memory_store: dict[str, CuratedMemoryEntry],
        markdown_entries: list[CuratedMemoryEntry],
    ) -> MarkdownSyncDelta:
        """Compare in-memory state against parsed markdown entries to find additions, updates, and deletions."""
        md_by_id = {e.entry_id: e for e in markdown_entries}
        added: list[CuratedMemoryEntry] = []
        updated: list[CuratedMemoryEntry] = []
        deleted_ids: list[str] = []

        # Find items added or updated in Markdown
        for entry_id, md_entry in md_by_id.items():
            if entry_id not in in_memory_store:
                added.append(md_entry)
            else:
                mem_entry = in_memory_store[entry_id]
                # Check for semantic differences
                if (
                    mem_entry.content != md_entry.content
                    or mem_entry.title != md_entry.title
                    or mem_entry.status != md_entry.status
                    or mem_entry.category != md_entry.category
                    or sorted(mem_entry.tags) != sorted(md_entry.tags)
                ):
                    # Preserve creation timestamp from in-memory
                    merged_entry = CuratedMemoryEntry(
                        entry_id=entry_id,
                        category=md_entry.category,
                        title=md_entry.title,
                        content=md_entry.content,
                        confidence=md_entry.confidence,
                        status=md_entry.status,
                        tags=list(md_entry.tags),
                        source_session_id=mem_entry.source_session_id,
                        created_at=mem_entry.created_at,
                        updated_at=datetime.now(UTC).isoformat(),
                    )
                    updated.append(merged_entry)

        # Find items deleted by human in Markdown
        for entry_id, mem_entry in in_memory_store.items():
            if entry_id not in md_by_id and mem_entry.status != CuratedMemoryStatus.ARCHIVED:
                deleted_ids.append(entry_id)

        return MarkdownSyncDelta(
            added_entries=added,
            updated_entries=updated,
            deleted_entry_ids=deleted_ids,
            sync_direction="markdown_to_ai",
        )

    def apply_sync(
        self,
        in_memory_store: dict[str, CuratedMemoryEntry],
        markdown_entries: list[CuratedMemoryEntry],
        hard_delete: bool = False,
    ) -> MarkdownSyncDelta:
        """Apply Markdown changes to in-memory store enforcing Human-in-the-loop precedence."""
        delta = self.compute_delta(in_memory_store, markdown_entries)

        # Apply additions
        for entry in delta.added_entries:
            in_memory_store[entry.entry_id] = entry

        # Apply updates
        for entry in delta.updated_entries:
            in_memory_store[entry.entry_id] = entry

        # Apply deletions (either tombstone archive or hard remove)
        for del_id in delta.deleted_entry_ids:
            if hard_delete:
                in_memory_store.pop(del_id, None)
            else:
                if del_id in in_memory_store:
                    in_memory_store[del_id].status = CuratedMemoryStatus.ARCHIVED
                    in_memory_store[del_id].updated_at = datetime.now(UTC).isoformat()

        return delta
