"""Intent slot tracker and confidence-guided extraction engine.

[INPUT]
Registered slot specifications, user conversation turns, and direct chip clicks.

[OUTPUT]
Slot state updates, missing slot detections, confidence scoring, and fact summaries.

[POS]
Maintains structured slot status matrix for proactive conversational convergence.
"""

import threading
from collections.abc import Mapping

from myrm_agent_harness.runtime.context.proactive_clarification_types import (
    IntentSlotSpec,
    SlotStateKind,
    SlotValueRecord,
)


class ProactiveSlotTracker:
    """Tracks and evaluates intent slots with confidence thresholds."""

    def __init__(self, slot_specs: list[IntentSlotSpec] | None = None) -> None:
        self._lock = threading.RLock()
        self._specs: dict[str, IntentSlotSpec] = {}
        self._records: dict[str, SlotValueRecord] = {}

        if slot_specs:
            self.register_slot_specs(slot_specs)

    def register_slot_specs(self, slot_specs: list[IntentSlotSpec]) -> None:
        """Register or extend the expected slot specifications."""
        with self._lock:
            for spec in slot_specs:
                self._specs[spec.name] = spec
                if spec.name not in self._records:
                    self._records[spec.name] = SlotValueRecord(
                        value=None,
                        state=SlotStateKind.EMPTY,
                        confidence_score=0.0,
                    )

    def fill_slot_explicitly(
        self,
        slot_name: str,
        value: str,
        confidence: float = 1.0,
        is_confirmed: bool = True,
        turn_index: int = 0,
    ) -> bool:
        """Directly populate a slot from user action chip selection or high-confidence input."""
        with self._lock:
            if slot_name not in self._specs:
                return False

            state = SlotStateKind.CONFIRMED if is_confirmed else SlotStateKind.INFERRED
            self._records[slot_name] = SlotValueRecord(
                value=value,
                state=state,
                confidence_score=confidence,
                source_turn_idx=turn_index,
            )
            return True

    def ingest_turn_heuristic(self, utterance: str, turn_index: int) -> int:
        """Heuristically extract matching choices and values from turn utterance."""
        with self._lock:
            updated_count = 0
            clean_text = utterance.strip().lower()

            for name, spec in self._specs.items():
                curr_rec = self._records[name]
                if curr_rec.state == SlotStateKind.CONFIRMED:
                    continue

                # Check if matches any allowed choices
                if spec.allowed_choices:
                    matched_choice: str | None = None
                    for choice in spec.allowed_choices:
                        if choice.lower() in clean_text:
                            matched_choice = choice
                            break

                    if matched_choice:
                        self._records[name] = SlotValueRecord(
                            value=matched_choice,
                            state=SlotStateKind.CONFIRMED,
                            confidence_score=0.95,
                            source_turn_idx=turn_index,
                        )
                        updated_count += 1
                        continue

                # Check simple key: value syntax like "tracking_number: 123456"
                prefix_patterns = (f"{name}:", f"{name}=", f"{spec.description.lower()}:")
                for prefix in prefix_patterns:
                    idx = clean_text.find(prefix)
                    if idx != -1:
                        val_start = idx + len(prefix)
                        raw_tail = utterance.strip()[val_start:].strip()
                        if raw_tail:
                            raw_val = raw_tail.split()[0].strip()
                            if raw_val:
                                self._records[name] = SlotValueRecord(
                                    value=raw_val,
                                    state=SlotStateKind.INFERRED,
                                    confidence_score=0.85,
                                    source_turn_idx=turn_index,
                                )
                                updated_count += 1
                                break

            return updated_count

    def get_missing_required_slots(self) -> list[str]:
        """Return names of required slots that are empty or below confidence threshold."""
        with self._lock:
            missing: list[str] = []
            for name, spec in self._specs.items():
                if not spec.required:
                    continue
                rec = self._records[name]
                if (
                    rec.state == SlotStateKind.EMPTY
                    or rec.value is None
                    or rec.confidence_score < spec.min_confidence_threshold
                ):
                    missing.append(name)
            return missing

    def is_fully_satisfied(self) -> bool:
        """Check if all required slots are adequately populated."""
        return len(self.get_missing_required_slots()) == 0

    def get_slot_records(self) -> Mapping[str, SlotValueRecord]:
        """Return current snapshot of all slot records."""
        with self._lock:
            return dict(self._records)

    def get_slot_spec(self, slot_name: str) -> IntentSlotSpec | None:
        """Retrieve spec definition for a slot."""
        with self._lock:
            return self._specs.get(slot_name)

    def get_summary_facts(self) -> dict[str, str]:
        """Aggregate confirmed and inferred facts into a dictionary."""
        with self._lock:
            return {
                name: rec.value
                for name, rec in self._records.items()
                if rec.value is not None and rec.state != SlotStateKind.EMPTY
            }
