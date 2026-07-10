"""Unit tests for perception/overlay_roles.py (SOM role SSOT)."""

from __future__ import annotations

from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef, BBox
from myrm_agent_harness.toolkits.computer_use.perception.overlay_roles import (
    normalize_desktop_role,
    is_interactive_for_overlay,
)


def test_normalize_desktop_role_maps_ax_button() -> None:
    assert normalize_desktop_role("AXButton") == "button"


def test_normalize_desktop_role_maps_text_field() -> None:
    assert normalize_desktop_role("AXTextField") == "textbox"


def test_normalize_desktop_role_unknown_falls_back_to_clickable() -> None:
    assert normalize_desktop_role("AXUnknownWidget") == "clickable"


def test_is_interactive_for_overlay_true_for_button() -> None:
    element = ElementRef(
        ref_id="d1",
        role="AXButton",
        name="OK",
        bbox=BBox(0, 0, 10, 10),
        backend_key="k",
    )
    assert is_interactive_for_overlay(element) is True


def test_is_interactive_for_overlay_false_for_static_text() -> None:
    element = ElementRef(
        ref_id="d2",
        role="AXStaticText",
        name="Label",
        bbox=BBox(0, 0, 10, 10),
        backend_key="k",
    )
    assert is_interactive_for_overlay(element) is False
