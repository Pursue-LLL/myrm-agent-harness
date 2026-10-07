"""Tests for Context Gap Auto Probe and Intent-Driven Proactive Recall Gate (Item 210).

Verifies pruned entity footprint extraction, static reference gap probing against active contexts,
autonomous recall nudge prompt generation, and noise suppression.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.proactive_recall.proactive_recall_engine import (
    ContextGapAutoProbeEngine,
)
from myrm_agent_harness.agent.context_management.proactive_recall.proactive_recall_types import (
    ContextGapDetection,
    EntityType,
    PrunedEntityRecord,
    ProactiveRecallNudgeConfig,
    ProactiveRecallProbeResult,
)


def test_heuristic_and_custom_entity_recording() -> None:
    """Verifies that technical entities are extracted from pruned text and stored losslessly."""
    engine = ContextGapAutoProbeEngine()
    session_id = "session_recall_alpha"

    pruned_text = (
        "During turn 3, we examined src/services/auth_manager.py and received "
        "ERR_AUTH_TIMEOUT when pinging https://api.service.internal/v1/auth. "
        "The function `handle_oauth_callback` was also inspected."
    )

    custom_record = PrunedEntityRecord(
        entity_name="DATABASE_MIGRATION_V2",
        entity_type=EntityType.CONFIG_KEY,
        turn_index=3,
        summary_hint="Database migration flag enabled in early setup",
    )

    records = engine.record_pruned_entities(
        session_id=session_id,
        turn_index=3,
        pruned_text=pruned_text,
        custom_entities=[custom_record],
    )

    assert len(records) >= 5

    stored = engine.get_pruned_entities(session_id)
    names = {r.entity_name for r in stored}

    assert "src/services/auth_manager.py" in names
    assert "https://api.service.internal/v1/auth" in names
    assert "ERR_AUTH_TIMEOUT" in names
    assert "handle_oauth_callback" in names
    assert "DATABASE_MIGRATION_V2" in names

    # Verify serialization
    serialized = custom_record.to_dict()
    assert serialized["entity_name"] == "DATABASE_MIGRATION_V2"
    assert serialized["entity_type"] == "config_key"
    assert serialized["turn_index"] == 3


def test_probe_context_gaps_with_proactive_nudge() -> None:
    """Verifies that referencing a pruned entity missing from the active window generates a nudge."""
    engine = ContextGapAutoProbeEngine()
    session_id = "session_recall_beta"

    # Pre-record pruned entity from earlier turn
    engine.record_pruned_entities(
        session_id=session_id,
        turn_index=5,
        pruned_text="Refactored src/core/crypto_signer.py with new key derivation.",
    )

    active_messages: list[dict[str, object]] = [
        {"role": "system", "content": "You are a software architect."},
        {"role": "assistant", "content": "We have completed the database setup."},
    ]

    current_input = (
        "Could you check if src/core/crypto_signer.py has any signature validation vulnerabilities?"
    )

    result: ProactiveRecallProbeResult = engine.probe_context_gaps(
        session_id=session_id,
        active_messages=active_messages,
        current_input=current_input,
    )

    assert result.has_gap is True
    assert len(result.detected_gaps) == 1
    gap = result.detected_gaps[0]
    assert gap.entity_name == "src/core/crypto_signer.py"
    assert gap.entity_type == EntityType.FILE_PATH
    assert gap.turn_index == 5
    assert "crypto_signer.py" in gap.context_snippet
    assert gap.confidence >= 0.8

    assert result.nudge_block is not None
    assert "<context-gap-nudge>" in result.nudge_block
    assert 'Entity "src/core/crypto_signer.py" (file_path) was discussed in Turn #5' in result.nudge_block
    assert "session_search" in result.nudge_block
    assert result.probe_latency_ms >= 0.0

    res_dict = result.to_dict()
    assert res_dict["has_gap"] is True
    assert res_dict["gap_count"] == 1


def test_no_gap_when_entity_already_present_or_irrelevant() -> None:
    """Verifies suppression when input does not reference pruned entities or active window defines it."""
    engine = ContextGapAutoProbeEngine()
    session_id = "session_recall_gamma"

    engine.record_pruned_entities(
        session_id=session_id,
        turn_index=2,
        pruned_text="Fixed bug in `validate_jwt_token`.",
    )

    # Case A: Input does not reference the pruned entity
    result_a = engine.probe_context_gaps(
        session_id=session_id,
        active_messages=[{"role": "assistant", "content": "Clean state."}],
        current_input="Please deploy the service to production.",
    )
    assert result_a.has_gap is False
    assert result_a.nudge_block is None

    # Case B: Input references the entity, but it is already fully present in active messages
    active_with_entity: list[dict[str, object]] = [
        {"role": "system", "content": "Here is validate_jwt_token implementation details."},
        {"role": "assistant", "content": "The validate_jwt_token function verifies HMAC SHA256."},
        {"role": "assistant", "content": "validate_jwt_token is already tested."},
    ]
    result_b = engine.probe_context_gaps(
        session_id=session_id,
        active_messages=active_with_entity,
        current_input="Let us modify validate_jwt_token.",
    )
    # Since validate_jwt_token is mentioned multiple times (>1) in active context, it's not missing
    assert result_b.has_gap is False
    assert result_b.nudge_block is None


def test_nudge_config_limits_and_session_clearing() -> None:
    """Verifies nudge cap, formatting toggles, and memory cleanup."""
    custom_cfg = ProactiveRecallNudgeConfig(
        max_nudges_per_turn=1,
        include_xml_wrapper=False,
    )
    engine = ContextGapAutoProbeEngine(default_config=custom_cfg)
    session_id = "session_recall_delta"

    engine.record_pruned_entities(
        session_id=session_id,
        turn_index=1,
        pruned_text="Investigated src/api/user.py and src/api/order.py.",
    )

    # Input references both pruned entities
    result = engine.probe_context_gaps(
        session_id=session_id,
        active_messages=[],
        current_input="Check both src/api/user.py and src/api/order.py.",
    )

    assert result.has_gap is True
    assert len(result.detected_gaps) == 1  # Capped at max_nudges_per_turn=1
    assert result.nudge_block is not None
    assert "<context-gap-nudge>" not in result.nudge_block  # include_xml_wrapper is False
    assert result.nudge_block.startswith("- Entity")

    # Clear session
    engine.clear_session(session_id)
    assert len(engine.get_pruned_entities(session_id)) == 0

    cleared_res = engine.probe_context_gaps(
        session_id=session_id,
        active_messages=[],
        current_input="Check src/api/user.py.",
    )
    assert cleared_res.has_gap is False
