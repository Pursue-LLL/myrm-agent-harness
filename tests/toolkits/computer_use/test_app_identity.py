"""Tests for stable desktop trust keys."""

from __future__ import annotations

from myrm_agent_harness.toolkits.computer_use.app_identity import resolve_trust_key, trust_key_matches


def test_resolve_trust_key_prefers_app_id() -> None:
    assert resolve_trust_key(app_name="Google Chrome", app_id="com.google.Chrome") == "com.google.Chrome"


def test_resolve_trust_key_falls_back_to_display_name() -> None:
    assert resolve_trust_key(app_name="Safari", app_id="") == "safari"


def test_trust_key_matches_legacy_display_name() -> None:
    assert trust_key_matches("safari", app_name="Safari", app_id="")


def test_trust_key_matches_empty_stored_key() -> None:
    assert trust_key_matches("", app_name="Safari", app_id="") is False
    assert trust_key_matches("   ", app_name="Safari", app_id="") is False


def test_trust_key_matches_app_id_candidate() -> None:
    assert trust_key_matches(
        "com.apple.Safari",
        app_name="Safari",
        app_id="com.apple.Safari",
    )


def test_trust_key_matches_display_name_when_app_id_differs() -> None:
    assert trust_key_matches(
        "safari",
        app_name="Safari",
        app_id="com.apple.Safari",
    )
