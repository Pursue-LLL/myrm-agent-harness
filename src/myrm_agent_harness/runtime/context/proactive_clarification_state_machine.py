"""Proactive clarification question generator and conversation convergence state machine.

[INPUT]
Slot tracker states, dialogue turns, and clarification interaction responses.

[OUTPUT]
Structured Action Chips payloads, convergence stagnation alerts, and tool execution gates.

[POS]
Orchestrates adaptive convergence state machine, preventing blind tool executions
and eliminating repetitive ambiguous multi-turn loops.
"""

import threading

from myrm_agent_harness.runtime.context.proactive_clarification_types import (
    ClarificationActionChip,
    ClarificationRequestPayload,
    ConvergenceAuditSnapshot,
    ConvergenceVerdict,
    SlotStateKind,
)
from myrm_agent_harness.runtime.context.proactive_slot_tracker import (
    ProactiveSlotTracker,
)


class ProactiveClarificationStateMachine:
    """State machine governing proactive questioning, chips generation, and convergence."""

    def __init__(
        self,
        slot_tracker: ProactiveSlotTracker,
        max_stagnant_turns: int = 2,
    ) -> None:
        self._tracker = slot_tracker
        self._max_stagnant_turns = max_stagnant_turns
        self._lock = threading.RLock()
        self._current_turn_index = 0
        self._stagnant_turns_count = 0
        self._last_filled_slots_count = 0

    def evaluate_turn(self, utterance: str) -> ConvergenceAuditSnapshot:
        """Process incoming user turn, update slots, and evaluate convergence progress."""
        with self._lock:
            self._current_turn_index += 1
            updated = self._tracker.ingest_turn_heuristic(
                utterance=utterance,
                turn_index=self._current_turn_index,
            )

            records = self._tracker.get_slot_records()
            total_count = len(records)
            filled_count = sum(
                1 for r in records.values() if r.state != SlotStateKind.EMPTY
            )
            confirmed_count = sum(
                1 for r in records.values() if r.state == SlotStateKind.CONFIRMED
            )

            # Check progress vs stagnation
            if self._tracker.is_fully_satisfied():
                self._stagnant_turns_count = 0
                verdict = ConvergenceVerdict.CONVERGED
            elif updated > 0 or filled_count > self._last_filled_slots_count:
                self._stagnant_turns_count = 0
                verdict = ConvergenceVerdict.PROGRESSING
            else:
                self._stagnant_turns_count += 1
                if self._stagnant_turns_count >= self._max_stagnant_turns:
                    verdict = ConvergenceVerdict.STAGNANT
                else:
                    verdict = ConvergenceVerdict.PROGRESSING

            self._last_filled_slots_count = filled_count

            return ConvergenceAuditSnapshot(
                turn_index=self._current_turn_index,
                total_slots_count=total_count,
                filled_slots_count=filled_count,
                confirmed_slots_count=confirmed_count,
                stagnant_turns_count=self._stagnant_turns_count,
                verdict=verdict,
                summary_of_known_facts=self._tracker.get_summary_facts(),
            )

    def generate_clarification_request(
        self, custom_prompt: str | None = None
    ) -> ClarificationRequestPayload | None:
        """Generate targeted clarification request with action chips if slots are missing."""
        with self._lock:
            missing = self._tracker.get_missing_required_slots()
            if not missing:
                return None

            primary_missing_slot = missing[0]
            spec = self._tracker.get_slot_spec(primary_missing_slot)

            chips: list[ClarificationActionChip] = []
            if spec and spec.allowed_choices:
                for idx, choice in enumerate(spec.allowed_choices):
                    chip_id = f"chip-{primary_missing_slot}-{idx}"
                    chips.append(
                        ClarificationActionChip(
                            chip_id=chip_id,
                            label=choice,
                            target_slot_name=primary_missing_slot,
                            slot_value=choice,
                            is_recommended=(idx == 0),
                        )
                    )

            if custom_prompt:
                question = custom_prompt
            elif spec:
                question = f"为了继续推进，请明确【{spec.description}】："
            else:
                question = f"请提供关键参数【{primary_missing_slot}】： "

            return ClarificationRequestPayload(
                question_text=question,
                missing_slot_names=tuple(missing),
                action_chips=tuple(chips),
                turn_index=self._current_turn_index,
                suppress_tool_execution=True,
            )

    def accept_chip_selection(self, chip: ClarificationActionChip) -> bool:
        """Apply user chip click directly to the slot tracker."""
        with self._lock:
            success = self._tracker.fill_slot_explicitly(
                slot_name=chip.target_slot_name,
                value=chip.slot_value,
                confidence=1.0,
                is_confirmed=True,
                turn_index=self._current_turn_index,
            )
            if success:
                self._stagnant_turns_count = 0
            return success

    def should_allow_tool_execution(self) -> bool:
        """Execution gate preventing premature tool use when required slots are missing."""
        with self._lock:
            return self._tracker.is_fully_satisfied()

    def get_audit_snapshot(self) -> ConvergenceAuditSnapshot:
        """Fetch current audit snapshot without advancing the turn."""
        with self._lock:
            records = self._tracker.get_slot_records()
            total_count = len(records)
            filled_count = sum(
                1 for r in records.values() if r.state != SlotStateKind.EMPTY
            )
            confirmed_count = sum(
                1 for r in records.values() if r.state == SlotStateKind.CONFIRMED
            )

            if self._tracker.is_fully_satisfied():
                verdict = ConvergenceVerdict.CONVERGED
            elif self._stagnant_turns_count >= self._max_stagnant_turns:
                verdict = ConvergenceVerdict.STAGNANT
            else:
                verdict = ConvergenceVerdict.PROGRESSING

            return ConvergenceAuditSnapshot(
                turn_index=self._current_turn_index,
                total_slots_count=total_count,
                filled_slots_count=filled_count,
                confirmed_slots_count=confirmed_count,
                stagnant_turns_count=self._stagnant_turns_count,
                verdict=verdict,
                summary_of_known_facts=self._tracker.get_summary_facts(),
            )
