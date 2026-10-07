"""Tests for Mid-Run Barge-In Steering and Non-Destructive Intervention Suite (Item 233)."""

import pytest

from myrm_agent_harness.agent.context_management.barge_in_steering import (
    BargeInMessage,
    BargeInSteeringConfig,
    InterventionMode,
    InterventionStatus,
    MidRunBargeInSteeringEngine,
    SteeringPointGateResult,
)


def test_mid_run_barge_in_steering_injection() -> None:
    """Verify in-flight user steering message is injected non-destructively at safe tool call boundaries."""
    config = BargeInSteeringConfig(steering_instruction_prefix="[MID-RUN BARGE-IN]: ")
    engine = MidRunBargeInSteeringEngine(config)
    session_id = "sess-barge-in-live"

    # Initially, safe gate detects no pending intervention
    gate_empty = engine.inspect_gate_and_inject(session_id, current_step_index=1)
    assert not gate_empty.has_intervention
    assert not gate_empty.should_suspend
    assert not gate_empty.is_hard_abort
    assert gate_empty.injected_message is None

    # User submits mid-run steering instruction while agent is generating code
    user_directive = "不要修改 CSS 样式，先帮我把导出 JSON 的格式调整为规范的 RFC8259 结构。"
    msg = engine.post_intervention(
        session_id=session_id,
        content=user_directive,
        mode=InterventionMode.BARGE_IN_STEER,
        metadata={"source": "voice_or_input_box"},
    )
    assert msg.session_id == session_id
    assert msg.mode == InterventionMode.BARGE_IN_STEER
    assert len(engine.get_pending_interventions(session_id)) == 1

    # Between tool step #2 and step #3, scheduler checks safe gate
    gate_result = engine.inspect_gate_and_inject(
        session_id=session_id,
        current_step_index=3,
        plan_summary="Generate CSS and JSON exporters",
    )

    assert gate_result.has_intervention
    assert not gate_result.should_suspend
    assert not gate_result.is_hard_abort
    assert gate_result.applied_intervention_id == msg.intervention_id
    assert gate_result.remaining_pending_count == 0

    injected = gate_result.injected_message
    assert injected is not None
    assert injected["role"] == "system"
    assert user_directive in injected["content"]
    assert "[MID-RUN BARGE-IN]: " in injected["content"]
    assert "DO NOT abort or wipe earlier completed progress" in injected["content"]
    assert "step #3" in injected["content"]

    # History contains consumed intervention
    history = engine.get_history(session_id)
    assert len(history) == 1
    assert history[0].intervention_id == msg.intervention_id


def test_hard_abort_gate_interception() -> None:
    """Verify hard abort disposition halts execution loop immediately and drains pending queue."""
    engine = MidRunBargeInSteeringEngine(BargeInSteeringConfig(drain_on_abort=True))
    session_id = "sess-abort-flow"

    # Queue an abort along with follow-ups
    engine.post_intervention(
        session_id=session_id,
        content="Stop completely immediately",
        mode=InterventionMode.HARD_ABORT,
    )
    engine.post_intervention(
        session_id=session_id,
        content="This should be drained",
        mode=InterventionMode.BARGE_IN_STEER,
    )

    gate_result = engine.inspect_gate_and_inject(session_id, current_step_index=5)
    assert gate_result.has_intervention
    assert gate_result.should_suspend
    assert gate_result.is_hard_abort
    assert gate_result.injected_message is None
    # Queue is completely drained
    assert len(engine.get_pending_interventions(session_id)) == 0


def test_queue_overflow_and_discard() -> None:
    """Verify bounded queue discards oldest items when exceeding max size and supports discard_pending."""
    engine = MidRunBargeInSteeringEngine(BargeInSteeringConfig(max_pending_queue_size=3))
    session_id = "sess-overflow"

    for i in range(5):
        engine.post_intervention(session_id, content=f"Intervention {i}")

    pending = engine.get_pending_interventions(session_id)
    assert len(pending) == 3
    # Kept latest items: 2, 3, 4
    assert pending[0].content == "Intervention 2"
    assert pending[2].content == "Intervention 4"

    # Purge queue
    purged_count = engine.discard_pending(session_id)
    assert purged_count == 3
    assert len(engine.get_pending_interventions(session_id)) == 0


def test_merge_incremental_intent() -> None:
    """Verify non-destructive synthesis of original user prompt with in-flight barge-in directive."""
    engine = MidRunBargeInSteeringEngine()
    session_id = "sess-intent-merge"

    intervention = engine.post_intervention(
        session_id=session_id,
        content="Change output directory to /tmp/dist",
        mode=InterventionMode.BARGE_IN_STEER,
    )

    merged = engine.merge_incremental_intent(
        original_prompt="Build and bundle the React application into default dir",
        intervention=intervention,
    )

    assert "Original Intent: Build and bundle the React application into default dir" in merged
    assert "Mid-Run User Correction (barge_in_steer): Change output directory to /tmp/dist" in merged
