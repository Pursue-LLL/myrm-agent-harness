"""Unit tests for Continual reset-free fault-site session overlays via continual namespace."""

from __future__ import annotations

from myrm_agent_harness.agent.continual.overlay import (
    DEFAULT_OVERLAY_TTL,
    DEFAULT_OVERLAY_TTL_TURNS,
    OverlayScope,
    OverlayShellType,
    OverlayStatus,
    OverlayTargetType,
    SessionOverlay,
    SessionOverlayManager,
    synthesize_fault_site_overlay,
)


def test_session_overlay_facade_and_constants() -> None:
    """Verify alias constants and shell types in continual facade."""
    assert DEFAULT_OVERLAY_TTL == 3
    assert DEFAULT_OVERLAY_TTL_TURNS == 3
    assert OverlayShellType.PROMPT_PATCH == OverlayTargetType.PROMPT_PATCH
    assert OverlayShellType.TEMP_SKILL_VARIANT == OverlayTargetType.TEMP_SKILL_VARIANT
    assert OverlayShellType.SUBAGENT_CONFIG == OverlayTargetType.SUBAGENT_CONFIG
    assert OverlayShellType.PROCEDURAL_MEMORY == OverlayTargetType.PROCEDURAL_MEMORY


def test_session_overlay_lifecycle_and_tick() -> None:
    """Test overlay immutability, tick countdown, and expiration."""
    overlay = SessionOverlay(
        overlay_id="ov_1",
        scope=OverlayScope.SESSION,
        target_type=OverlayTargetType.PROMPT_PATCH,
        target_name="global",
        patch_payload={"advisory_instruction": "Test advisory"},
        failure_signature="Test trigger",
        ttl_turns=3,
    )
    assert overlay.status == OverlayStatus.ACTIVE
    assert overlay.is_alive() is True
    assert overlay.remaining_turns == 3
    assert overlay.trigger_reason == "Test trigger"
    assert overlay.shell_type == OverlayTargetType.PROMPT_PATCH
    assert overlay.patch_data["advisory_instruction"] == "Test advisory"


def test_overlay_manager_continual_integration() -> None:
    """Test overlay manager apply, advisory lookup, and tick via continual facade."""
    manager = SessionOverlayManager()
    ovl = synthesize_fault_site_overlay(
        tool_name="stripe_charges",
        error="RateLimitError: 429 Too Many Requests on stripe_charges",
        tool_args={"limit": 50},
        current_turn=1,
    )
    assert ovl is not None
    manager.apply_overlay(ovl)

    advisories = manager.get_advisories()
    assert len(advisories) > 0
    assert any("stripe_charges" in adv for adv in advisories)

    # Tick 3 turns to reach expiration
    manager.tick(current_turn=2)
    manager.tick(current_turn=3)
    manager.tick(current_turn=4)

    assert len(manager.get_active_overlays()) == 0
    assert len(manager.get_advisories()) == 0
