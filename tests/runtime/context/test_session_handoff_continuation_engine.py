"""Unit tests for Session Handoff and Clean Window Continuation Engine.

Part of Item 126: SessionHandoffCleanWindowContinuationEngine.
Verifies handoff lifecycle state machine, prompt compilation with 8-part structure,
prevention of secondary pitfall re-attempts, token savings calculations, and thread safety.
"""

from __future__ import annotations

import concurrent.futures

import pytest

from myrm_agent_harness.runtime.context.session_handoff_continuation_engine import (
    SessionHandoffContinuationEngine,
)
from myrm_agent_harness.runtime.context.session_handoff_continuation_types import (
    HandoffPhaseKind,
    HandoffTriggerReason,
    RejectedAlternativeRecord,
    StructuredHandoffMemo,
)


def _build_sample_memo(session_id: str = "sess-alpha-001") -> StructuredHandoffMemo:
    """Helper creating a comprehensive sample 8-part handoff memorandum."""
    return StructuredHandoffMemo(
        memo_id="memo-999",
        source_session_id=session_id,
        created_at="2026-10-07T12:00:00Z",
        trigger_reason=HandoffTriggerReason.CAPACITY_SATURATION,
        current_objective="Migrate auth subsystem to zero-trust device binding",
        completed_milestones=[
            "Extracted legacy session token middleware",
            "Added JWT signature validation tests",
        ],
        active_hypotheses=[
            "Device key pair can be stored in secure enclave",
        ],
        rejected_alternatives=[
            RejectedAlternativeRecord(
                proposed_approach="Plain cookie-based token fallback",
                failure_reason="Violates Zero-Trust SOC2 compliance audit requirement",
                prevent_retry=True,
            ),
            RejectedAlternativeRecord(
                proposed_approach="In-memory global state cache for active handshakes",
                failure_reason="Causes race conditions across multi-worker cluster restarts",
                prevent_retry=True,
            ),
        ],
        critical_constraints=[
            "Strict 0 Any typing across all new schemas",
            "Zero backwards incompatible DB migrations without approval",
        ],
        next_action_plan=[
            "Implement EnclaveDeviceKeyStore in runtime/security",
            "Run full regression test suite across auth modules",
        ],
        modified_files_and_artifacts=[
            "src/myrm_agent_harness/security/device_binding.py",
            "tests/security/test_device_binding.py",
        ],
        external_state_anchors={
            "git_commit": "abc1234",
            "target_branch": "feature/device-binding",
        },
    )


def test_handoff_lifecycle_happy_path() -> None:
    """Verify happy-path transition: PREPARING -> READY_FOR_SHIFT -> TRANSFERRED."""
    engine = SessionHandoffContinuationEngine()
    source_session_id = "sess-100"
    new_session_id = "sess-101"

    handoff_id = engine.initiate_handoff(
        source_session_id=source_session_id,
        trigger_reason=HandoffTriggerReason.CAPACITY_SATURATION,
    )
    assert engine.get_phase(handoff_id) == HandoffPhaseKind.PREPARING

    memo = _build_sample_memo(session_id=source_session_id)
    engine.submit_memo(handoff_id=handoff_id, memo=memo)
    assert engine.get_phase(handoff_id) == HandoffPhaseKind.READY_FOR_SHIFT

    bundle = engine.generate_clean_window_bundle(
        handoff_id=handoff_id,
        new_session_id=new_session_id,
        source_context_tokens=80_000,
    )
    assert bundle.source_session_id == source_session_id
    assert bundle.new_session_id == new_session_id
    assert bundle.estimated_token_savings_pct > 90.0

    committed = engine.commit_transfer(handoff_id)
    assert committed is True
    assert engine.get_phase(handoff_id) == HandoffPhaseKind.TRANSFERRED


def test_handoff_lifecycle_abort_flow() -> None:
    """Verify aborting an active handoff."""
    engine = SessionHandoffContinuationEngine()
    handoff_id = engine.initiate_handoff("sess-200")
    assert engine.get_phase(handoff_id) == HandoffPhaseKind.PREPARING

    engine.abort_handoff(handoff_id, reason="User cancelled session shift")
    assert engine.get_phase(handoff_id) == HandoffPhaseKind.ABORTED


def test_invalid_phase_transitions_guard() -> None:
    """Verify state invariants block premature operations."""
    engine = SessionHandoffContinuationEngine()
    handoff_id = engine.initiate_handoff("sess-300")

    # Trying to generate bundle before memo is submitted must raise ValueError
    with pytest.raises(ValueError, match="Cannot generate bundle in phase"):
        engine.generate_clean_window_bundle(handoff_id, "new-sess", 50_000)

    # Submitting memo after abort must raise ValueError
    engine.abort_handoff(handoff_id)
    memo = _build_sample_memo("sess-300")
    with pytest.raises(ValueError, match="Cannot submit memo in state"):
        engine.submit_memo(handoff_id, memo)


def test_bootstrap_prompt_compilation_and_rejected_alternatives_guard() -> None:
    """Verify prompt compiler generates 8-part structure with hard-coded rejection warnings."""
    engine = SessionHandoffContinuationEngine()
    memo = _build_sample_memo("sess-400")
    prompt = engine.compile_bootstrap_prompt(memo)

    assert "<session_handoff_context>" in prompt
    assert "</session_handoff_context>" in prompt
    assert "## 1. Primary Objective" in prompt
    assert "Migrate auth subsystem" in prompt
    assert "## 2. Completed Milestones" in prompt
    assert "Extracted legacy session token middleware" in prompt
    assert "## 4. Rejected Alternatives & Disqualifications (DO NOT RE-ATTEMPT)" in prompt
    assert "Plain cookie-based token fallback" in prompt
    assert "Violates Zero-Trust SOC2 compliance audit requirement" in prompt
    assert "In-memory global state cache for active handshakes" in prompt
    assert "## 5. Critical Constraints & Principles" in prompt
    assert "Strict 0 Any typing across all new schemas" in prompt
    assert "## 6. Actionable Next Steps" in prompt
    assert "## 7. Modified Files & Artifacts" in prompt
    assert "## 8. External State Anchors" in prompt
    assert "git_commit" in prompt


def test_token_savings_computation() -> None:
    """Verify context token savings percentage is computed correctly."""
    engine = SessionHandoffContinuationEngine()
    handoff_id = engine.initiate_handoff("sess-500")
    memo = _build_sample_memo("sess-500")
    engine.submit_memo(handoff_id, memo)

    bundle = engine.generate_clean_window_bundle(
        handoff_id=handoff_id,
        new_session_id="fresh-sess-501",
        source_context_tokens=100_000,
    )
    # 100,000 source tokens reclaimed to ~500 tokens -> >95% savings
    assert bundle.estimated_token_savings_pct > 95.0
    assert bundle.source_context_tokens == 100_000
    assert bundle.handoff_memo_tokens > 0


def test_multithreaded_concurrent_handoff_safety() -> None:
    """Verify concurrent thread execution of multiple handoffs without race conditions."""
    engine = SessionHandoffContinuationEngine()

    def process_handoff(idx: int) -> None:
        source_id = f"sess-threaded-{idx}"
        target_id = f"sess-fresh-{idx}"
        hid = engine.initiate_handoff(source_id)
        memo = _build_sample_memo(source_id)
        engine.submit_memo(hid, memo)
        b = engine.generate_clean_window_bundle(hid, target_id, 50_000)
        assert b.new_session_id == target_id
        engine.commit_transfer(hid)
        assert engine.get_phase(hid) == HandoffPhaseKind.TRANSFERRED

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(process_handoff, i) for i in range(20)]
        concurrent.futures.wait(futures)

    assert len(engine._phases) == 20
