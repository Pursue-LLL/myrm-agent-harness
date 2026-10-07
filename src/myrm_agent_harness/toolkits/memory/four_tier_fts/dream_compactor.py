"""[POS]: src/myrm_agent_harness/toolkits/memory/four_tier_fts/dream_compactor.py
[INPUT]: SqliteFts5MemoryEngine, project hashes, and compaction configurations.
[OUTPUT]: FourTierDreamCompactor executing /dream maintenance cycles, deduplicating fragments, and purging stale progress items.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from .fts_engine import SqliteFts5MemoryEngine
from .models import DreamCompactionReport, FourTierMemoryItem, MemoryScope


class FourTierDreamCompactor:
    """Orchestrates /dream maintenance cycles to compact duplicate fragments and purge ephemeral progress."""

    def __init__(self, engine: SqliteFts5MemoryEngine) -> None:
        self._engine = engine

    def run_dream_cycle(
        self,
        project_hash: str = "default",
        purge_progress_days: int = 7,
    ) -> DreamCompactionReport:
        """Executes a /dream compaction run for the specified project."""
        start_time = time.perf_counter()
        dream_id = f"dream_{uuid.uuid4().hex[:8]}"

        items = self._engine.list_items(project_hash=project_hash)
        scanned_count = len(items)
        merged_count = 0
        pruned_count = 0

        now = datetime.now(UTC)

        # 1. Prune expired or stale PROGRESS items older than purge_progress_days
        for it in items:
            if it.scope == MemoryScope.PROGRESS:
                age_days = (now - it.updated_at).total_seconds() / 86400.0
                if age_days >= purge_progress_days:
                    self._engine.delete_item(it.item_id, project_hash=project_hash)
                    pruned_count += 1

        # Re-fetch remaining items after pruning
        remaining_items = self._engine.list_items(project_hash=project_hash)

        # 2. Merge fragments with matching scope and title
        # (scope, title.strip().lower()) -> list of FourTierMemoryItem
        grouped: dict[tuple[MemoryScope, str], list[FourTierMemoryItem]] = {}
        for it in remaining_items:
            key = (it.scope, it.title.strip().lower())
            grouped.setdefault(key, []).append(it)

        for (_scope, _normalized_title), group in grouped.items():
            if len(group) > 1:
                # Keep the latest item, append distinct content bullets from older items
                group.sort(key=lambda x: x.updated_at, reverse=True)
                primary = group[0]
                merged_lines: list[str] = [primary.content]

                for secondary in group[1:]:
                    if secondary.content not in primary.content:
                        merged_lines.append(f"\n--- Consolidated from {secondary.item_id} ---\n{secondary.content}")
                    # Delete the merged secondary item
                    self._engine.delete_item(secondary.item_id, project_hash=project_hash)
                    merged_count += 1

                # Update primary item with combined content and distinct tags
                all_tags = set(primary.tags)
                for sec in group[1:]:
                    all_tags.update(sec.tags)

                primary.content = "\n".join(merged_lines)
                primary.tags = sorted(all_tags)
                self._engine.save_item(primary)

        # Count final retained items
        final_items = self._engine.list_items(project_hash=project_hash)
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return DreamCompactionReport(
            dream_id=dream_id,
            scanned_items_count=scanned_count,
            merged_items_count=merged_count,
            pruned_items_count=pruned_count,
            retained_items_count=len(final_items),
            duration_ms=duration_ms,
            created_at=now,
        )
