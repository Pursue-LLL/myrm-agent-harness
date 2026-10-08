"""Compaction buffer implementing validate-before-purge and bounded rollback stash.

[INPUT]
- CompactionEntry: History turn or message entry.
- CompactionRollbackBudget: Rules governing verification limits and maximum rollback capacity.

[OUTPUT]
- CompactionRollbackBuffer: Stash manager providing transactional compaction replacement and rollback.
- validate_summary_candidate: Verifier inspecting replacement candidate before old history is touched.

[POS]
Transactional compaction replacement and bounded rollback stash engine.
"""

from __future__ import annotations

from typing import Sequence
import uuid

from .nested_approval_types import (
    CompactionEntry,
    CompactionRollbackBudget,
)


def validate_summary_candidate(
    candidate: CompactionEntry,
    budget: CompactionRollbackBudget,
) -> tuple[bool, str | None]:
    """Validate candidate compaction entry before any historical data is purged."""
    if not candidate.content or not candidate.content.strip():
        return False, "Candidate compaction summary content cannot be empty"

    if candidate.token_count <= 0:
        return False, f"Invalid token count in summary candidate: {candidate.token_count}"

    if candidate.token_count > budget.max_token_ceiling:
        return False, (
            f"Candidate summary tokens ({candidate.token_count}) exceed ceiling ({budget.max_token_ceiling})"
        )

    return True, None


class CompactionRollbackBuffer:
    """Manages transactional history compaction replacements with bounded rollback buffers."""

    def __init__(self) -> None:
        # Keyed by stash_id -> tuple of preserved old entries
        self._stashes: dict[str, tuple[CompactionEntry, ...]] = {}

    def validate_and_replace(
        self,
        existing_history: Sequence[CompactionEntry],
        candidate_summary: CompactionEntry,
        budget: CompactionRollbackBudget,
    ) -> tuple[bool, tuple[CompactionEntry, ...], str | None, str | None]:
        """Validate candidate first; only purge old history and stash rollback if valid."""
        # 1. Step 1: Validate first before touching existing history
        if budget.validation_enabled:
            is_valid, error = validate_summary_candidate(candidate_summary, budget)
            if not is_valid:
                # Return immediately without touching existing history
                return False, tuple(existing_history), None, error

        # 2. Step 2: Separate preserved recent tail turns from old historical entries
        total_len = len(existing_history)
        split_point = max(0, total_len - budget.min_retained_turns)

        to_compact = tuple(existing_history[:split_point])
        recent_tail = tuple(existing_history[split_point:])

        # 3. Step 3: Stash old entries under bounded rollback budget
        stash_entries = to_compact[-budget.max_rollback_entries :]
        stash_id = f"stash_{uuid.uuid4().hex[:12]}"
        self._stashes[stash_id] = stash_entries

        # 4. Step 4: Construct new history = candidate_summary + preserved recent tail
        new_history = (candidate_summary, *recent_tail)
        return True, new_history, stash_id, None

    def rollback(
        self,
        stash_id: str,
        current_history: Sequence[CompactionEntry],
    ) -> tuple[CompactionEntry, ...]:
        """Restore previous history entries from bounded rollback stash."""
        stashed = self._stashes.get(stash_id)
        if stashed is None:
            raise KeyError(f"Rollback stash '{stash_id}' not found or already purged")

        # Recombine stashed old entries with whatever tail entries exist after summary
        if len(current_history) > 1:
            tail_entries = current_history[1:]
            return (*stashed, *tail_entries)
        return stashed

    def discard_stash(self, stash_id: str) -> bool:
        """Purge stash after commit is fully finalized."""
        return self._stashes.pop(stash_id, None) is not None
