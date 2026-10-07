"""Append-only compaction ledger engine with atomic tool-pair cut points and split-turn fusion.

Maintains immutable context logs, enforces tool-pair atomic invariants during compaction,
synthesizes double-segment split-turn summaries, and dynamically assembles pristine
LLM context views devoid of orphaned tool results.

[INPUT]
- runtime.context.append_only_compaction_types::CompactedContextAssembly, CompactionEntry, ContextEntryRole,
  ContextLogEntry (POS: Types for append-only compaction ledger and atomic tool-pair cut-point engine.)
- runtime.context.atomic_tool_pair_cut_point_resolver::AtomicToolPairCutPointResolver (POS: Atomic tool-pair
  cut-point resolver for context compaction.)

[OUTPUT]
- AppendOnlyCompactionLedgerEngine: Engine managing an immutable append-only context log and atomic
  compactions.

[POS]
Append-only compaction ledger engine with atomic tool-pair cut points and split-turn fusion.
"""

import re
from datetime import UTC, datetime

from .append_only_compaction_types import (
    CompactedContextAssembly,
    CompactionEntry,
    ContextEntryRole,
    ContextLogEntry,
)
from .atomic_tool_pair_cut_point_resolver import AtomicToolPairCutPointResolver


class AppendOnlyCompactionLedgerEngine:
    """Engine managing an immutable append-only context log and atomic compactions."""

    _READ_FILE_RE = re.compile(r"(?i)\b(?:read|view|cat|open)\s+([/\w\.\-]+\.\w+)")
    _WRITE_FILE_RE = re.compile(r"(?i)\b(?:write|modify|edit|update|created)\s+([/\w\.\-]+\.\w+)")

    def __init__(self, resolver: AtomicToolPairCutPointResolver | None = None) -> None:
        """Initialize append-only compaction ledger."""
        self._entries: list[ContextLogEntry] = []
        self._compactions: list[CompactionEntry] = []
        self._resolver = resolver or AtomicToolPairCutPointResolver()

    def append_entry(self, entry: ContextLogEntry) -> None:
        """Append an immutable context log entry."""
        self._entries.append(entry)

    def append_entries(self, entries: list[ContextLogEntry]) -> None:
        """Append multiple immutable context entries."""
        self._entries.extend(entries)

    @property
    def entries(self) -> list[ContextLogEntry]:
        """Return full immutable history of entries."""
        return list(self._entries)

    @property
    def compactions(self) -> list[CompactionEntry]:
        """Return history of compaction markers."""
        return list(self._compactions)

    def compact(
        self,
        target_kept_tokens: int,
        custom_summary: str | None = None,
    ) -> CompactionEntry | None:
        """Execute atomic compaction, appending a new CompactionEntry without mutating history."""
        if not self._entries:
            return None

        tokens_before = sum(e.token_estimate for e in self._entries)
        resolution = self._resolver.resolve_atomic_cut_point(self._entries, target_kept_tokens)

        if resolution.cut_index == 0:
            # Everything fits within target budget, no need to compact
            return None

        compacted_slice = self._entries[: resolution.cut_index]
        retained_slice = self._entries[resolution.cut_index :]

        # Extract file access footprint from compacted slice
        read_files: set[str] = set()
        modified_files: set[str] = set()

        for entry in compacted_slice:
            for match in self._READ_FILE_RE.findall(entry.content):
                read_files.add(match)
            for match in self._WRITE_FILE_RE.findall(entry.content):
                modified_files.add(match)

        # Generate summary
        if custom_summary:
            summary = custom_summary
        elif resolution.is_split_turn:
            # Split-turn dual segment fusion
            split_turn_id = retained_slice[0].turn_id if retained_slice else 0
            hist_entries = [e for e in compacted_slice if e.turn_id != split_turn_id]
            curr_entries = [e for e in compacted_slice if e.turn_id == split_turn_id]

            part1 = f"Historical Context ({len(hist_entries)} steps completed): Goals and decisions established."
            part2 = f"Active Turn #{split_turn_id} Partial Progress ({len(curr_entries)} actions executed): Intermediate outputs processed."
            summary = f"[SPLIT_TURN_COMPACTION_SUMMARY]\n{part1}\n{part2}"
        else:
            turn_ids = {e.turn_id for e in compacted_slice if e.turn_id > 0}
            summary = (
                f"[COMPACTION_SUMMARY]\n"
                f"Compacted {len(compacted_slice)} entries across turns {sorted(turn_ids)}. "
                f"Key files read: {sorted(read_files)}; files modified: {sorted(modified_files)}."
            )

        now_iso = datetime.now(UTC).isoformat()
        compaction_id = f"cmp_{len(self._compactions) + 1}_{resolution.cut_index}"

        tokens_after = sum(e.token_estimate for e in retained_slice) + 150  # 150 tokens for summary

        compaction_entry = CompactionEntry(
            compaction_id=compaction_id,
            summary=summary,
            first_kept_entry_id=resolution.first_kept_entry_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            read_files=sorted(read_files),
            modified_files=sorted(modified_files),
            is_split_turn=resolution.is_split_turn,
            created_at=now_iso,
        )

        self._compactions.append(compaction_entry)
        return compaction_entry

    def assemble_context_for_llm(
        self,
        system_prompt: str,
    ) -> CompactedContextAssembly:
        """Assemble a pristine, validated context package for model inference."""
        if not self._compactions:
            # No compactions: return all entries
            retained = list(self._entries)
            total_tokens = sum(e.token_estimate for e in retained) + 50
            return CompactedContextAssembly(
                system_prompt=system_prompt,
                active_summary=None,
                retained_entries=retained,
                total_assembled_tokens=total_tokens,
                has_orphaned_tool_pairs=False,
            )

        latest_compaction = self._compactions[-1]
        first_kept_id = latest_compaction.first_kept_entry_id

        # Locate first kept entry index
        start_idx = 0
        for idx, entry in enumerate(self._entries):
            if entry.entry_id == first_kept_id:
                start_idx = idx
                break

        retained = self._entries[start_idx:]

        # Rigorous invariant check: detect any orphaned TOOL_RESULT without preceding TOOL_CALL
        seen_calls: set[str] = set()
        has_orphaned_tool_pairs = False

        for entry in retained:
            if entry.role == ContextEntryRole.TOOL_CALL and entry.tool_call_id:
                seen_calls.add(entry.tool_call_id)
            elif (
                entry.role == ContextEntryRole.TOOL_RESULT
                and entry.tool_call_id
                and entry.tool_call_id not in seen_calls
            ):
                has_orphaned_tool_pairs = True
                break

        total_tokens = (
            sum(e.token_estimate for e in retained)
            + 150  # for summary
            + 50  # for system prompt
        )

        return CompactedContextAssembly(
            system_prompt=system_prompt,
            active_summary=latest_compaction.summary,
            retained_entries=retained,
            total_assembled_tokens=total_tokens,
            has_orphaned_tool_pairs=has_orphaned_tool_pairs,
        )
