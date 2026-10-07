"""Tests for SessionAntiPoisoningEngine and 1-Click Antidote Suite (Item 225)."""

import pytest

from myrm_agent_harness.agent.context_management.session_antidote import (
    AntidoteReceipt,
    ConfigMutationProposal,
    FlagScope,
    PoisonSeverity,
    SessionAntiPoisoningEngine,
    SessionAntidoteConfig,
)


def test_genesis_registration_and_checksum_immutability() -> None:
    """Verify genesis baseline registration generates SHA256 checksum and maintains snapshot."""
    engine = SessionAntiPoisoningEngine()
    session_id = "sess-test-genesis-01"
    base_flags = {
        "model_temperature": "0.2",
        "context_window_limit": "128000",
        "safe_mode": "true",
    }

    snapshot = engine.register_genesis_config(session_id, base_flags)
    assert snapshot.session_id == session_id
    assert snapshot.base_flags == base_flags
    assert len(snapshot.checksum) == 64  # valid SHA256 hex digest

    # Verify effective flags match genesis baseline
    effective = engine.get_effective_flags(session_id)
    assert effective == base_flags

    # Baseline diagnosis must be CLEAN
    diagnosis = engine.diagnose_session_health(session_id, effective)
    assert diagnosis.severity == PoisonSeverity.CLEAN
    assert len(diagnosis.detected_drifts) == 0


def test_blocked_dangerous_flags_and_ephemeral_turn_sandboxing() -> None:
    """Verify dangerous flags are blocked without approval, and autonomous flags are sandboxed to turn."""
    engine = SessionAntiPoisoningEngine()
    session_id = "sess-fable-poison-scenario"
    engine.register_genesis_config(session_id, {"safe_mode": "true"})

    # 1. Model attempts to autonomously activate dangerous flag (Fable reproduction)
    dangerous_proposal = ConfigMutationProposal(
        source="autonomous_model",
        requested_flags={"fast_ultra_mode": "true", "skip_all_safety_checks": "true"},
        explicit_user_approved=False,
    )
    accepted, reason, scope = engine.evaluate_mutation(session_id, dangerous_proposal)
    assert not accepted
    assert scope == FlagScope.REJECTED_BLOCKED
    assert "Blocked dangerous flag" in reason

    # 2. Autonomous benign flag gets sandboxed to turn scope only
    benign_proposal = ConfigMutationProposal(
        source="autonomous_model",
        requested_flags={"concise_mode": "true"},
        explicit_user_approved=False,
    )
    accepted, reason, scope = engine.evaluate_mutation(session_id, benign_proposal)
    assert accepted
    assert scope == FlagScope.EPHEMERAL_TURN

    # Apply to turn 1
    engine.apply_turn_ephemeral_flags(session_id, "turn-1", {"concise_mode": "true"})
    assert engine.get_effective_flags(session_id, "turn-1")["concise_mode"] == "true"

    # Turn 2 has not received turn-1 flags
    assert "concise_mode" not in engine.get_effective_flags(session_id, "turn-2")

    # Finalize turn-1: ephemeral flags are cleanly disposed
    engine.finalize_turn_cleanup(session_id, "turn-1")
    assert "concise_mode" not in engine.get_effective_flags(session_id, "turn-1")


def test_watchdog_drift_and_poisoning_detection() -> None:
    """Verify watchdog correctly flags configuration drifts and severe poisoning."""
    engine = SessionAntiPoisoningEngine(SessionAntidoteConfig(max_drift_tolerance=2))
    session_id = "sess-watchdog-eval"
    engine.register_genesis_config(session_id, {"baseline_flag": "stable"})

    # Case A: Slight drift (unregistered benign flag)
    drifted_runtime = {"baseline_flag": "stable", "random_flag_x": "val1"}
    diag = engine.diagnose_session_health(session_id, drifted_runtime)
    assert diag.severity == PoisonSeverity.SUSPICIOUS
    assert len(diag.detected_drifts) == 1

    # Case B: Multiple drifts exceeding tolerance
    multi_drift = {
        "baseline_flag": "stable",
        "random_flag_x": "val1",
        "random_flag_y": "val2",
    }
    diag_multi = engine.diagnose_session_health(session_id, multi_drift)
    assert diag_multi.severity == PoisonSeverity.POTENTIALLY_POISONED

    # Case C: Dangerous active flag in runtime -> SEVERELY_POISONED
    poisoned_runtime = {
        "baseline_flag": "stable",
        "disable_tool_sandboxing": "true",
    }
    diag_poison = engine.diagnose_session_health(session_id, poisoned_runtime)
    assert diag_poison.severity == PoisonSeverity.SEVERELY_POISONED
    assert "disable_tool_sandboxing" in diag_poison.offending_flags


def test_one_click_antidote_atomic_rollback_and_preservation() -> None:
    """Verify 1-Click Antidote completely purges all poison and restores genesis while keeping dialog turns."""
    engine = SessionAntiPoisoningEngine()
    session_id = "sess-antidote-recovery"
    genesis_flags = {
        "temperature": "0.3",
        "safe_mode": "enforced",
        "context_cap": "64000",
    }
    snapshot = engine.register_genesis_config(session_id, genesis_flags)

    # User explicitly approves a custom flag, modifying persistent state
    user_proposal = ConfigMutationProposal(
        source="user_request",
        requested_flags={"experimental_feature": "beta", "temperature": "0.9"},
        explicit_user_approved=True,
    )
    engine.evaluate_mutation(session_id, user_proposal)

    # Verify persistent state mutated
    current_effective = engine.get_effective_flags(session_id)
    assert current_effective["experimental_feature"] == "beta"
    assert current_effective["temperature"] == "0.9"

    # Also stage active ephemeral flags in turn-5
    engine.apply_turn_ephemeral_flags(session_id, "turn-5", {"extra_noise": "true"})

    # Execute 1-Click Antidote preserving 42 completed dialog turns
    receipt: AntidoteReceipt = engine.apply_one_click_antidote(
        session_id=session_id,
        preserved_turns_count=42,
    )

    # Check receipt
    assert receipt.session_id == session_id
    assert "experimental_feature" in receipt.purged_flags
    assert receipt.restored_flags_count == 3
    assert receipt.preserved_turns_count == 42
    assert receipt.restored_to_checksum == snapshot.checksum

    # Verify runtime is 100% restored to exact Genesis state
    restored_effective = engine.get_effective_flags(session_id, "turn-5")
    assert restored_effective == genesis_flags
    assert "extra_noise" not in restored_effective
    assert restored_effective["temperature"] == "0.3"

    # Diagnosis is now CLEAN
    final_diag = engine.diagnose_session_health(session_id, restored_effective)
    assert final_diag.severity == PoisonSeverity.CLEAN
