"""Tests for the desktop semantic control HITL gate.

Covers the AX interact gate (mutating actions + interactive roles + shared
lexicon), the coordinate bbox hit-testing resolver, and the vision coordinate
gate — including the fail-closed path when no LangGraph context exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.computer_use.coordinate_scaler import CoordinateScaler
from myrm_agent_harness.toolkits.computer_use.dref.types import BBox, ElementRef
from myrm_agent_harness.toolkits.computer_use.semantic_gate import (
    DesktopGuardContext,
    enforce_desktop_interact_guard,
    enforce_desktop_vision_guard,
    resolve_coordinate_target,
)

_SCALER = CoordinateScaler(
    screen_width=1280,
    screen_height=800,
    sent_width=640,
    sent_height=400,
    dpi_scale=2.0,
)


def _ctx(
    *,
    app_name: str = "Navicat",
    window_title: str = "Inventory — PostgreSQL",
    with_screenshot: bool = True,
    scaler: CoordinateScaler | None = _SCALER,
) -> DesktopGuardContext:
    async def provider() -> tuple[str, tuple[int, int]]:
        return ("Z3VhcmQtZXZpZGVuY2U=", (640, 400)) if with_screenshot else ("", (0, 0))

    return DesktopGuardContext(
        app_name=app_name,
        window_title=window_title,
        screenshot_provider=provider if with_screenshot else None,
        scaler=scaler,
    )


def _elem(
    ref_id: str,
    role: str = "AXButton",
    name: str = "Export Report",
    bbox: tuple[int, int, int, int] = (100, 100, 200, 40),
) -> ElementRef:
    return ElementRef(
        ref_id=ref_id,
        role=role,
        name=name,
        bbox=BBox(*bbox),
        backend_key="k",
    )


# ──────────────────────────────────────────────────────────────────
# AX interact gate — preconditions
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("action", ["hover", "focus", "scroll", "fill", "set_value", "type", "expand", "collapse"])
async def test_non_activating_actions_pass(action: str):
    with patch("langgraph.types.interrupt") as mock_interrupt:
        result = await enforce_desktop_interact_guard(
            ctx=_ctx(),
            ref_id="d1",
            role="AXButton",
            name="Delete All Records",
            action=action,
        )
    assert result is None
    mock_interrupt.assert_not_called()


async def test_static_text_role_never_gated():
    with patch("langgraph.types.interrupt") as mock_interrupt:
        result = await enforce_desktop_interact_guard(
            ctx=_ctx(),
            ref_id="d1",
            role="AXStaticText",
            name="删除全部记录",
            action="click",
        )
    assert result is None
    mock_interrupt.assert_not_called()


async def test_benign_interactive_control_passes():
    with patch("langgraph.types.interrupt") as mock_interrupt:
        result = await enforce_desktop_interact_guard(
            ctx=_ctx(),
            ref_id="d1",
            role="AXButton",
            name="Export Report",
            action="click",
        )
    assert result is None
    mock_interrupt.assert_not_called()


@pytest.mark.parametrize("action", ["click", "dblclick", "press", "invoke", "toggle", "check", "uncheck"])
async def test_activation_actions_on_high_risk_control_interrupt(action: str):
    with patch("langgraph.types.interrupt", return_value={"decision": "approve"}) as mock_interrupt:
        result = await enforce_desktop_interact_guard(
            ctx=_ctx(),
            ref_id="d42",
            role="AXButton",
            name="Delete All Records",
            action=action,
        )
    assert result is None
    mock_interrupt.assert_called_once()


async def test_chinese_lexicon_high_risk():
    with patch("langgraph.types.interrupt", return_value={"decision": "reject"}):
        result = await enforce_desktop_interact_guard(
            ctx=_ctx(),
            ref_id="d7",
            role="AXButton",
            name="删除全部记录",
            action="click",
        )
    assert result is not None
    assert "[BLOCKED]" in result


# ──────────────────────────────────────────────────────────────────
# AX interact gate — HITL payload, approval, rejection, fail-closed
# ──────────────────────────────────────────────────────────────────


async def test_interrupt_payload_carries_desktop_context_and_screenshot():
    with patch("langgraph.types.interrupt", return_value={"decision": "approve"}) as mock_interrupt:
        result = await enforce_desktop_interact_guard(
            ctx=_ctx(),
            ref_id="d42",
            role="AXButton",
            name="Delete All Records",
            action="click",
        )
    assert result is None
    payload = mock_interrupt.call_args[0][0]
    assert payload["action_type"] == "high_risk_dom_action"
    assert payload["surface"] == "desktop"
    assert payload["tool_name"] == "desktop_interact_tool"
    assert payload["app_name"] == "Navicat"
    assert payload["window_title"] == "Inventory — PostgreSQL"
    assert payload["element"] == {"role": "AXButton", "name": "Delete All Records", "ref": "d42"}
    assert payload["screenshot_base64"] == "Z3VhcmQtZXZpZGVuY2U="
    assert payload["screenshot_size"] == [640, 400]


async def test_rejection_returns_block_message_with_feedback():
    with patch("langgraph.types.interrupt", return_value={"decision": "reject", "feedback": "Export instead"}):
        result = await enforce_desktop_interact_guard(
            ctx=_ctx(),
            ref_id="d42",
            role="AXButton",
            name="Drop Database",
            action="click",
        )
    assert result is not None
    assert "[BLOCKED]" in result
    assert "Export instead" in result
    assert "alternative approach" in result


async def test_no_graph_context_fails_closed():
    with patch("langgraph.types.interrupt", side_effect=RuntimeError("no graph context")):
        result = await enforce_desktop_interact_guard(
            ctx=_ctx(),
            ref_id="d42",
            role="AXButton",
            name="Drop Database",
            action="click",
        )
    assert result is not None
    assert "[BLOCKED]" in result
    assert "alternative approach" in result


async def test_screenshot_provider_failure_still_interrupts():
    async def broken_provider() -> tuple[str, tuple[int, int]]:
        raise RuntimeError("screen unavailable")

    ctx = DesktopGuardContext(
        app_name="Navicat",
        window_title="Inventory",
        screenshot_provider=broken_provider,
        scaler=_SCALER,
    )
    with patch("langgraph.types.interrupt", return_value={"decision": "approve"}) as mock_interrupt:
        result = await enforce_desktop_interact_guard(
            ctx=ctx,
            ref_id="d42",
            role="AXButton",
            name="Terminate Cluster",
            action="click",
        )
    assert result is None
    payload = mock_interrupt.call_args[0][0]
    assert "screenshot_base64" not in payload


# ──────────────────────────────────────────────────────────────────
# Coordinate resolver — bbox hit-testing
# ──────────────────────────────────────────────────────────────────


def _refs(*elements: object) -> Mapping[str, object]:
    refs: dict[str, object] = {}
    for element in elements:
        assert isinstance(element, ElementRef)
        refs[element.ref_id] = element
    return refs


def test_smallest_area_wins_over_container():
    container = _elem("d0", role="AXTabGroup", name="Settings Pane", bbox=(0, 0, 1280, 800))
    button = _elem("d1", role="AXButton", name="Terminate Cluster", bbox=(100, 100, 200, 40))
    # Image coordinate (50, 55) → screen (100, 110) hits both container and button.
    target = resolve_coordinate_target(scaler=_SCALER, refs=_refs(container, button), image_x=50, image_y=55)
    assert target is not None
    assert target.ref_id == "d1"


def test_coordinate_outside_all_bboxes_returns_none():
    button = _elem("d1", role="AXButton", name="Terminate Cluster", bbox=(100, 100, 200, 40))
    target = resolve_coordinate_target(scaler=_SCALER, refs=_refs(button), image_x=600, image_y=390)
    assert target is None


def test_non_interactive_role_bbox_ignored():
    label = _elem("d1", role="AXStaticText", name="删除全部记录", bbox=(100, 100, 200, 40))
    target = resolve_coordinate_target(scaler=_SCALER, refs=_refs(label), image_x=50, image_y=55)
    assert target is None


def test_non_element_ref_values_skipped():
    target = resolve_coordinate_target(
        scaler=_SCALER,
        refs={"d1": "not-an-element"},
        image_x=50,
        image_y=55,
    )
    assert target is None


# ──────────────────────────────────────────────────────────────────
# Vision coordinate gate
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("action", ["left_click", "right_click", "double_click", "triple_click", "drag"])
async def test_coordinate_actions_on_high_risk_target_interrupt(action: str):
    button = _elem("d9", role="AXButton", name="Terminate Cluster", bbox=(100, 100, 200, 40))
    with patch("langgraph.types.interrupt", return_value={"decision": "approve"}) as mock_interrupt:
        result = await enforce_desktop_vision_guard(
            ctx=_ctx(),
            refs=_refs(button),
            action=action,
            coordinate=[50, 55],
        )
    assert result is None
    mock_interrupt.assert_called_once()
    payload = mock_interrupt.call_args[0][0]
    assert payload["tool_name"] == "desktop_vision_tool"
    assert payload["element"]["name"] == "Terminate Cluster"
    # Highlight is the target bbox center (200, 120 screen) converted back into image space (100, 60).
    assert payload["highlight_coordinate"] == [100, 60]


async def test_non_coordinate_vision_actions_pass():
    button = _elem("d9", role="AXButton", name="Terminate Cluster", bbox=(100, 100, 200, 40))
    with patch("langgraph.types.interrupt") as mock_interrupt:
        result = await enforce_desktop_vision_guard(
            ctx=_ctx(),
            refs=_refs(button),
            action="type",
            coordinate=[50, 55],
        )
    assert result is None
    mock_interrupt.assert_not_called()


async def test_unresolvable_coordinate_passes():
    with patch("langgraph.types.interrupt") as mock_interrupt:
        result = await enforce_desktop_vision_guard(
            ctx=_ctx(),
            refs={},
            action="left_click",
            coordinate=[50, 55],
        )
    assert result is None
    mock_interrupt.assert_not_called()


async def test_missing_scaler_passes():
    button = _elem("d9", role="AXButton", name="Terminate Cluster", bbox=(100, 100, 200, 40))
    with patch("langgraph.types.interrupt") as mock_interrupt:
        result = await enforce_desktop_vision_guard(
            ctx=_ctx(scaler=None),
            refs=_refs(button),
            action="left_click",
            coordinate=[50, 55],
        )
    assert result is None
    mock_interrupt.assert_not_called()


async def test_resolved_benign_target_passes():
    button = _elem("d9", role="AXButton", name="Refresh View", bbox=(100, 100, 200, 40))
    with patch("langgraph.types.interrupt") as mock_interrupt:
        result = await enforce_desktop_vision_guard(
            ctx=_ctx(),
            refs=_refs(button),
            action="left_click",
            coordinate=[50, 55],
        )
    assert result is None
    mock_interrupt.assert_not_called()


async def test_out_of_bounds_coordinate_passes():
    button = _elem("d9", role="AXButton", name="Terminate Cluster", bbox=(100, 100, 200, 40))
    with patch("langgraph.types.interrupt") as mock_interrupt:
        result = await enforce_desktop_vision_guard(
            ctx=_ctx(),
            refs=_refs(button),
            action="left_click",
            coordinate=[5000, 5000],
        )
    assert result is None
    mock_interrupt.assert_not_called()
