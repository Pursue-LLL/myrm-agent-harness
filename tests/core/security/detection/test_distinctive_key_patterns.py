"""Tests for the vendor-prefix shapes a precision-first gate may refuse a message on."""

from __future__ import annotations

from myrm_agent_harness.core.security.detection import leak_detector
from myrm_agent_harness.core.security.detection.leak_detector import DISTINCTIVE_KEY_PATTERNS

_ALL_NAMES = {name for name, _ in leak_detector._API_KEY_PATTERNS}
_DISTINCTIVE_NAMES = {name for name, _ in DISTINCTIVE_KEY_PATTERNS}


def test_the_weak_shapes_are_all_in_the_vendor_table() -> None:
    """A misspelt name in the weak list would silently promote a weak shape to refusal grade."""
    assert leak_detector._WEAK_PREFIX_KEY_NAMES <= _ALL_NAMES


def test_distinctive_shapes_are_the_vendor_table_without_the_weak_ones() -> None:
    assert _DISTINCTIVE_NAMES == _ALL_NAMES - leak_detector._WEAK_PREFIX_KEY_NAMES


def test_a_shape_that_an_identifier_can_spell_is_not_distinctive() -> None:
    assert {"vercel_token", "fal_key"}.isdisjoint(_DISTINCTIVE_NAMES)
    identifiers = ("vercel_request_handler_name_for_edge_functions", "fal_select_the_image_model_for_this_request")
    assert not [name for name, pattern in DISTINCTIVE_KEY_PATTERNS for text in identifiers if pattern.search(text)]


def test_a_shape_with_a_short_prefix_or_a_hex_body_is_not_distinctive() -> None:
    assert (
        not {"firecrawl_key", "elevenlabs_key", "cloudflare_token", "twilio_key", "databricks_token"}
        & _DISTINCTIVE_NAMES
    )


def test_the_vendors_a_user_pastes_most_are_distinctive() -> None:
    assert {
        "groq_key",
        "huggingface_token",
        "tavily_key",
        "perplexity_key",
        "npm_token",
        "github_token",
    } <= _DISTINCTIVE_NAMES
