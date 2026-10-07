"""Unit tests for ProactiveClarificationStateMachine and ProactiveSlotTracker.

Validates active inquiry, slot extraction, action chips, and convergence loop breaking,
benchmarked against Bairong BR-LLM-Proactive architecture.
"""

from concurrent.futures import ThreadPoolExecutor

from myrm_agent_harness.runtime.context.proactive_clarification_state_machine import (
    ProactiveClarificationStateMachine,
)
from myrm_agent_harness.runtime.context.proactive_clarification_types import (
    ClarificationActionChip,
    ConvergenceVerdict,
    IntentSlotSpec,
    SlotStateKind,
)
from myrm_agent_harness.runtime.context.proactive_slot_tracker import (
    ProactiveSlotTracker,
)


def _build_logistics_slots() -> list[IntentSlotSpec]:
    """Helper creating realistic logistics query slot specifications."""
    return [
        IntentSlotSpec(
            name="carrier",
            description="物流承运商",
            required=True,
            expected_type="choice",
            allowed_choices=("顺丰速运", "中通快递", "京东物流"),
            min_confidence_threshold=0.80,
        ),
        IntentSlotSpec(
            name="tracking_number",
            description="快递运单号",
            required=True,
            expected_type="string",
            min_confidence_threshold=0.75,
        ),
        IntentSlotSpec(
            name="priority_level",
            description="催派优先级",
            required=False,
            expected_type="choice",
            allowed_choices=("普通", "加急", "特急"),
        ),
    ]


def test_slot_registration_and_heuristic_extraction() -> None:
    """Verifies slot registration and natural language heuristic extraction."""
    tracker = ProactiveSlotTracker(_build_logistics_slots())
    assert not tracker.is_fully_satisfied()
    assert tracker.get_missing_required_slots() == ["carrier", "tracking_number"]

    # Turn 1: utterance mentions carrier choice
    updated = tracker.ingest_turn_heuristic("我想查一下顺丰速运的快件", turn_index=1)
    assert updated == 1
    records = tracker.get_slot_records()
    assert records["carrier"].state == SlotStateKind.CONFIRMED
    assert records["carrier"].value == "顺丰速运"
    assert records["carrier"].confidence_score >= 0.90

    # Turn 2: utterance provides tracking number key: value
    updated2 = tracker.ingest_turn_heuristic("tracking_number: SF1008699", turn_index=2)
    assert updated2 == 1
    records2 = tracker.get_slot_records()
    assert records2["tracking_number"].state == SlotStateKind.INFERRED
    assert records2["tracking_number"].value == "SF1008699"

    # Now both required slots are adequately populated
    assert tracker.is_fully_satisfied()
    assert len(tracker.get_missing_required_slots()) == 0
    facts = tracker.get_summary_facts()
    assert facts["carrier"] == "顺丰速运"
    assert facts["tracking_number"] == "SF1008699"


def test_missing_required_slots_and_action_chips_generation() -> None:
    """Verifies that missing slots trigger targeted clarification requests with chips."""
    tracker = ProactiveSlotTracker(_build_logistics_slots())
    machine = ProactiveClarificationStateMachine(slot_tracker=tracker, max_stagnant_turns=2)

    # Initially tools must be suppressed
    assert not machine.should_allow_tool_execution()

    req = machine.generate_clarification_request()
    assert req is not None
    assert req.suppress_tool_execution is True
    assert "carrier" in req.missing_slot_names
    assert len(req.action_chips) == 3

    chip_labels = [c.label for c in req.action_chips]
    assert "顺丰速运" in chip_labels
    assert "京东物流" in chip_labels
    assert req.action_chips[0].is_recommended is True


def test_action_chip_selection_and_instant_resolution() -> None:
    """Verifies that one-click chip click directly confirms slot and satisfies gate."""
    tracker = ProactiveSlotTracker(_build_logistics_slots())
    machine = ProactiveClarificationStateMachine(slot_tracker=tracker, max_stagnant_turns=2)

    # 1. Fill carrier via chip
    selected_chip = ClarificationActionChip(
        chip_id="chip-carrier-0",
        label="顺丰速运",
        target_slot_name="carrier",
        slot_value="顺丰速运",
    )
    ok = machine.accept_chip_selection(selected_chip)
    assert ok is True
    assert tracker.get_slot_records()["carrier"].state == SlotStateKind.CONFIRMED

    # Still missing tracking_number
    assert not machine.should_allow_tool_execution()

    # 2. Fill tracking number via user input
    machine.evaluate_turn("运单号 tracking_number: 998877")
    assert machine.should_allow_tool_execution()

    # Once satisfied, clarification request is None
    assert machine.generate_clarification_request() is None


def test_dialogue_convergence_and_stagnation_loop_breaker() -> None:
    """Verifies that repetitive ambiguous turns trigger STAGNANT alert instead of looping."""
    tracker = ProactiveSlotTracker(_build_logistics_slots())
    machine = ProactiveClarificationStateMachine(slot_tracker=tracker, max_stagnant_turns=2)

    # Turn 1: ambiguous utterance, no slot filled
    snap1 = machine.evaluate_turn("你快点帮我查一下，很急")
    assert snap1.verdict == ConvergenceVerdict.PROGRESSING
    assert snap1.stagnant_turns_count == 1

    # Turn 2: second ambiguous turn with zero progress -> triggers STAGNANT
    snap2 = machine.evaluate_turn("怎么还没查到？")
    assert snap2.verdict == ConvergenceVerdict.STAGNANT
    assert snap2.stagnant_turns_count == 2

    # Still suppresses tools
    assert not machine.should_allow_tool_execution()


def test_multithreaded_concurrency_and_audit_snapshot() -> None:
    """Verifies thread-safety under concurrent turns and chip updates."""
    tracker = ProactiveSlotTracker(_build_logistics_slots())
    machine = ProactiveClarificationStateMachine(slot_tracker=tracker, max_stagnant_turns=5)

    def _turn_worker(idx: int) -> ConvergenceVerdict:
        if idx % 2 == 0:
            machine.accept_chip_selection(
                ClarificationActionChip(
                    chip_id=f"chip-carrier-{idx}",
                    label="顺丰速运",
                    target_slot_name="carrier",
                    slot_value="顺丰速运",
                )
            )
        snap = machine.evaluate_turn(f"turn comment {idx}")
        return snap.verdict

    with ThreadPoolExecutor(max_workers=4) as pool:
        verdicts = list(pool.map(_turn_worker, range(8)))

    assert len(verdicts) == 8
    final_audit = machine.get_audit_snapshot()
    assert final_audit.turn_index == 8
    assert final_audit.total_slots_count == 3
