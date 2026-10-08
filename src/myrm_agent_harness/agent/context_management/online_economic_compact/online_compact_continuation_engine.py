# [INPUT]: CompactionDecisionResult, ContinuationTurnPayload, EconomicCompactionLedger, PlanStep
# [OUTPUT]: OnlineCompactContinuationEngine
# [POS]: agent/context_management/online_economic_compact/online_compact_continuation_engine.py

"""Online compaction continuation engine providing smooth new-turn handoffs.

[INPUT]
- CompactionDecisionResult, ContinuationTurnPayload, EconomicCompactionLedger, PlanStep:
  Domain models from economic_compact_types.

[OUTPUT]
- OnlineCompactContinuationEngine: State machine synthesizing structured memos, updating economic
  ledgers, and assembling continuation payloads for subsequent execution turns.

[POS]
Execution bridge orchestrating post-compaction state transitions and prompt continuity.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .economic_compact_types import (
    CompactionDecisionResult,
    ContinuationTurnPayload,
    EconomicCompactionLedger,
    PlanStep,
)


class OnlineCompactContinuationEngine:
    """Executes state resets, memo distillation, and prompt reconstruction for new turns."""

    def __init__(self, ledger: EconomicCompactionLedger | None = None) -> None:
        self._ledger = ledger or EconomicCompactionLedger()

    @property
    def ledger(self) -> EconomicCompactionLedger:
        return self._ledger

    def generate_memo_summary(
        self,
        messages: Sequence[Mapping[str, str]],
        completed_steps: Sequence[PlanStep],
        remaining_steps: Sequence[PlanStep],
    ) -> str:
        """Synthesize a structured memo capturing verified milestones and active context."""
        completed_titles = [f"- [x] {s.title} (spent {s.requests_spent} reqs)" for s in completed_steps]
        remaining_titles = [f"- [ ] {s.title}" for s in remaining_steps]

        memo_sections: list[str] = [
            "### [SUBTASK MILESTONE MEMO]",
            "#### Completed Milestones:",
            "\n".join(completed_titles) if completed_titles else "- (No milestones completed yet)",
            "#### Remaining Plan Steps:",
            "\n".join(remaining_titles) if remaining_titles else "- (All planned steps completed)",
            f"#### Historical Context Digest: Synthesized across {len(messages)} prior operational turns.",
        ]
        return "\n\n".join(memo_sections)

    def assemble_continuation_prompt(
        self,
        memo_summary: str,
        remaining_steps: Sequence[PlanStep],
        next_turn_number: int,
    ) -> str:
        """Assemble the system instruction seamlessly bootstrapping the new agent turn."""
        next_step_focus = remaining_steps[0].title if remaining_steps else "Final goal verification and conclusion"
        return (
            f"[CONTINUATION TURN {next_turn_number} BOOTSTRAP]\n"
            "Context from prior subtasks has been economically compacted to eliminate redundant tokens.\n\n"
            f"{memo_summary}\n\n"
            f"CURRENT OBJECTIVE: Focus immediately on executing: '{next_step_focus}'.\n"
            "Proceed with the next necessary operation without requesting repeated context."
        )

    def execute_continuation(
        self,
        messages: Sequence[Mapping[str, str]],
        decision: CompactionDecisionResult,
        completed_steps: Sequence[PlanStep],
        remaining_steps: Sequence[PlanStep],
        current_tokens: int,
        session_turn: int = 1,
    ) -> ContinuationTurnPayload:
        """Perform turn transition, update amortization ledger, and return turn payload."""
        next_turn = session_turn + 1
        memo = self.generate_memo_summary(
            messages=messages,
            completed_steps=completed_steps,
            remaining_steps=remaining_steps,
        )
        prompt = self.assemble_continuation_prompt(
            memo_summary=memo,
            remaining_steps=remaining_steps,
            next_turn_number=next_turn,
        )

        # Update cumulative economic accounting ledger
        self._ledger.total_compactions += 1
        self._ledger.last_compaction_tokens = current_tokens
        self._ledger.lifetime_tokens_saved += decision.net_estimated_savings

        # Amortize or carry debt
        if decision.reason_code == "ECONOMIC_BREAKEVEN_APPROVED":
            self._ledger.carried_debt_tokens = 0
        else:
            # If compacted due to hard pressure without full breakeven, record carried debt
            memo_tokens_estimate = len(memo.split()) * 2
            compaction_write_cost = 2400
            self._ledger.carried_debt_tokens = max(0, compaction_write_cost - (current_tokens - memo_tokens_estimate))

        return ContinuationTurnPayload(
            new_turn_number=next_turn,
            memo_summary=memo,
            remaining_steps=remaining_steps,
            continuation_prompt=prompt,
        )
