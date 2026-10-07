"""Atomic tool-pair cut-point resolver for context compaction.

Guarantees the Atomic Tool-Pair Invariant: prevents severed tool_call and
tool_result pairs, eradicates orphaned Tool Result 400 API errors, and handles
split-turn scenarios for ultra-large turns.

[INPUT]
- runtime.context.append_only_compaction_types::ContextEntryRole, ContextLogEntry, CutPointResolution (POS:
  Types for append-only compaction ledger and atomic tool-pair cut-point engine.)

[OUTPUT]
- AtomicToolPairCutPointResolver: Calculates safe compaction cut points respecting tool-pair atomic
  boundaries.

[POS]
Atomic tool-pair cut-point resolver for context compaction.
"""

from .append_only_compaction_types import (
    ContextEntryRole,
    ContextLogEntry,
    CutPointResolution,
)


class AtomicToolPairCutPointResolver:
    """Calculates safe compaction cut points respecting tool-pair atomic boundaries."""

    def resolve_atomic_cut_point(
        self,
        entries: list[ContextLogEntry],
        target_kept_tokens: int,
    ) -> CutPointResolution:
        """Resolve a safe cut point where no tool_call and tool_result pair is severed."""
        if not entries:
            return CutPointResolution(
                cut_index=0,
                first_kept_entry_id="",
                is_split_turn=False,
                retained_tokens=0,
                adjustment_reason="Empty entries list",
            )

        total_tokens = sum(e.token_estimate for e in entries)
        if total_tokens <= target_kept_tokens:
            # Everything fits within budget, no compaction required
            return CutPointResolution(
                cut_index=0,
                first_kept_entry_id=entries[0].entry_id,
                is_split_turn=False,
                retained_tokens=total_tokens,
                adjustment_reason="Entire history fits within target kept tokens",
            )

        # Step 1: Accumulate tokens from the tail backwards to find initial target cut index
        accumulated_tokens = 0
        raw_cut_index = len(entries) - 1

        for i in range(len(entries) - 1, -1, -1):
            accumulated_tokens += entries[i].token_estimate
            if accumulated_tokens >= target_kept_tokens:
                raw_cut_index = i
                break

        # Step 2: Build map of tool_call_id to entries for invariant validation
        tool_call_map: dict[str, int] = {}  # tool_call_id -> index of TOOL_CALL
        tool_result_map: dict[str, int] = {}  # tool_call_id -> index of TOOL_RESULT

        for idx, entry in enumerate(entries):
            if entry.tool_call_id:
                if entry.role == ContextEntryRole.TOOL_CALL:
                    tool_call_map[entry.tool_call_id] = idx
                elif entry.role == ContextEntryRole.TOOL_RESULT:
                    tool_result_map[entry.tool_call_id] = idx

        # Step 3: Snap cut point to adhere to Atomic Tool-Pair Invariant
        adjusted_cut_index = raw_cut_index
        adjustment_reason = "Natural token budget boundary"

        # Check if any TOOL_RESULT in the retained segment [cut_index:] is missing its TOOL_CALL
        # Or if cut_index landed strictly on a TOOL_RESULT
        while adjusted_cut_index < len(entries):
            candidate_entry = entries[adjusted_cut_index]

            # Invariant A: Cannot start retained segment on a TOOL_RESULT
            if candidate_entry.role == ContextEntryRole.TOOL_RESULT:
                call_id = candidate_entry.tool_call_id
                if call_id and call_id in tool_call_map:
                    # Move cut point backwards to include the parent TOOL_CALL
                    call_idx = tool_call_map[call_id]
                    if call_idx < adjusted_cut_index:
                        adjusted_cut_index = call_idx
                        adjustment_reason = (
                            f"Atomic snap backwards to include parent TOOL_CALL for {call_id}"
                        )
                        continue
                else:
                    # Orphaned result or missing call, skip past this result to keep tail clean
                    adjusted_cut_index += 1
                    adjustment_reason = "Advanced past unanchored tool result"
                    continue

            # Invariant B: Ensure no tool_call in the compacted prefix has a retained result
            violation_found = False
            for t_id, res_idx in tool_result_map.items():
                if res_idx >= adjusted_cut_index:
                    call_idx = tool_call_map.get(t_id)
                    if call_idx is not None and call_idx < adjusted_cut_index:
                        # Severed pair! Pull cut_index backwards to the TOOL_CALL
                        adjusted_cut_index = call_idx
                        adjustment_reason = (
                            f"Prevented severed pair for {t_id}: pulled cut to TOOL_CALL"
                        )
                        violation_found = True
                        break

            if not violation_found:
                break

        # Invariant C: Conversational boundary handling vs Split-Turn
        is_split_turn = False
        if entries[adjusted_cut_index].role == ContextEntryRole.TOOL_CALL:
            candidate_backtrack = adjusted_cut_index
            while candidate_backtrack > 0 and entries[candidate_backtrack].role != ContextEntryRole.USER:
                candidate_backtrack -= 1
            backtrack_tokens = sum(e.token_estimate for e in entries[candidate_backtrack:])
            if backtrack_tokens > target_kept_tokens * 1.2 and candidate_backtrack < adjusted_cut_index:
                is_split_turn = True
                adjustment_reason = "Split-turn triggered at atomic tool-pair boundary for oversized turn"
            else:
                adjusted_cut_index = candidate_backtrack
                adjustment_reason = "Backtracked to clean conversational boundary"
        else:
            while adjusted_cut_index > 0:
                current_role = entries[adjusted_cut_index].role
                if current_role in (
                    ContextEntryRole.USER,
                    ContextEntryRole.ASSISTANT,
                    ContextEntryRole.CUSTOM,
                ):
                    break
                adjusted_cut_index -= 1
                adjustment_reason = "Backtracked to clean conversational boundary"

        # Step 4: Detect split-turn conditions when single turn spans boundary
        retained = entries[adjusted_cut_index:]
        retained_tokens = sum(e.token_estimate for e in retained)

        if not is_split_turn and len(retained) > 0 and adjusted_cut_index > 0:
            first_kept_turn = retained[0].turn_id
            last_compacted_turn = entries[adjusted_cut_index - 1].turn_id
            if first_kept_turn == last_compacted_turn and first_kept_turn > 0:
                is_split_turn = True
                adjustment_reason += " (Split-turn triggered within large single turn)"

        first_kept_id = entries[adjusted_cut_index].entry_id if adjusted_cut_index < len(entries) else ""

        return CutPointResolution(
            cut_index=adjusted_cut_index,
            first_kept_entry_id=first_kept_id,
            is_split_turn=is_split_turn,
            retained_tokens=retained_tokens,
            adjustment_reason=adjustment_reason,
        )
