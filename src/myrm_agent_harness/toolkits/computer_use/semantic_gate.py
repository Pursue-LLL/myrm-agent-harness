"""Semantic desktop control HITL gate — destructive control interception.

Layers desktop-specific action preconditions (AX activation actions, interactive
role filtering, coordinate bbox hit-testing) on top of the shared cross-channel
destructive element lexicon from ``core.security.detection.semantic_risk``, so
a mutating activation on a dangerous desktop control is gated identically to
its browser DOM counterpart regardless of which channel performs it.

[INPUT]
- core.security.detection.semantic_risk::SemanticRiskLevel, RiskVerdict,
  classify_element_risk (POS: 跨通道破坏性控件语义词典 SSOT)
- dref.types::ElementRef, INTERACTIVE_AX_ROLES (POS: AX 元素引用与可交互角色集)
- coordinate_scaler::CoordinateScaler (POS: 截图图像空间↔屏幕空间双向转换)
- langgraph.types::interrupt (POS: HITL interrupt 机制)
- core.security.audit::record_decision (POS: 安全决策审计)

[OUTPUT]
- enforce_desktop_interact_guard: desktop_interact AX 激活动作语义门
- resolve_coordinate_target: vision 坐标→AX 元素最小面积 bbox 反查
- enforce_desktop_vision_guard: desktop_vision 坐标动作语义门

[POS]
桌面双轴语义门。desktop_interact（@dref AX 语义轴）与 desktop_vision_action
（坐标 bbox 反查轴）共享 core 词典；fail-closed：无 LangGraph 上下文时阻断而非放行。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, NamedTuple

from myrm_agent_harness.core.security.detection.semantic_risk import (
    SemanticRiskLevel,
    classify_element_risk,
)
from myrm_agent_harness.toolkits.computer_use.dref.types import (
    INTERACTIVE_AX_ROLES,
    ElementRef,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.computer_use.coordinate_scaler import (
        CoordinateScaler,
    )

logger = logging.getLogger(__name__)

# AX activation actions that mutate application state on the target control.
# Text-entry actions (fill / set_value / type / fill_credential) submit nothing
# by themselves — the final submit control is gated instead. Navigation-free
# actions (hover / focus / scroll / expand / collapse) are read-only.
_DESKTOP_MUTATING_ACTIONS = frozenset(
    {
        "click",
        "dblclick",
        "press",
        "invoke",
        "toggle",
        "check",
        "uncheck",
    }
)

# Vision coordinate actions whose landing point identifies the mutation target
# (drag lands on its end coordinate).
_VISION_COORDINATE_ACTIONS = frozenset(
    {
        "left_click",
        "right_click",
        "middle_click",
        "double_click",
        "triple_click",
        "drag",
    }
)

ScreenshotProvider = Callable[[], Awaitable[tuple[str, tuple[int, int]]]]


class DesktopGuardContext(NamedTuple):
    """Session-level context the desktop semantic gate reports to the user."""

    app_name: str
    window_title: str
    screenshot_provider: ScreenshotProvider | None
    scaler: CoordinateScaler | None


def _parse_interrupt_decision(user_response: object) -> bool:
    if isinstance(user_response, dict):
        return user_response.get("decision") == "approve"
    if isinstance(user_response, str):
        return user_response.lower() in ("approve", "allow", "yes", "y")
    return False


def _user_rejection_feedback(user_response: object) -> str:
    if isinstance(user_response, dict):
        return str(user_response.get("feedback", "") or "")
    return ""


async def _require_hitl_approval(
    *,
    ctx: DesktopGuardContext,
    tool_name: str,
    reason: str,
    tool_input: dict[str, object],
    element: dict[str, str] | None = None,
    highlight_screen_xy: tuple[int, int] | None = None,
) -> str | None:
    """Return a block message when the user rejects; None when approved."""
    from langgraph.types import interrupt

    from myrm_agent_harness.core.security.audit import record_decision

    logger.warning(
        "[DESKTOP_SEMANTIC_GUARD] High-risk action blocked for approval: tool=%s app=%s reason=%s",
        tool_name,
        ctx.app_name,
        reason,
    )

    record_decision(tool_name, "ASK", f"Desktop semantic guard: {reason}")

    hitl_payload: dict[str, object] = {
        "action_type": "high_risk_dom_action",
        "surface": "desktop",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "reason": reason,
        "app_name": ctx.app_name,
        "window_title": ctx.window_title,
    }
    if element is not None:
        hitl_payload["element"] = element

    # Evidence screenshot with the target landing point circled in image space,
    # so the approval card can render a red-ring annotation on any screen size.
    if ctx.screenshot_provider is not None:
        try:
            screenshot_b64, screenshot_size = await ctx.screenshot_provider()
            if screenshot_b64:
                hitl_payload["screenshot_base64"] = screenshot_b64
                hitl_payload["screenshot_size"] = list(screenshot_size)
                if highlight_screen_xy is not None and ctx.scaler is not None:
                    hitl_payload["highlight_coordinate"] = list(
                        ctx.scaler.screen_to_api(*highlight_screen_xy)
                    )
        except Exception as exc:
            logger.debug("Desktop semantic guard screenshot capture failed: %s", exc)

    try:
        user_response = interrupt(hitl_payload)
    except RuntimeError:
        # Fail-closed: without a LangGraph execution context no human can ever
        # confirm this action, so a high-risk target must be blocked instead of
        # silently auto-approved (unattended paths must not bypass the gate).
        record_decision(tool_name, "NO_CONTEXT_DENIED", "No LangGraph context — fail-closed deny")
        return (
            "[BLOCKED] High-risk action requires human approval, but no interactive agent "
            f"session is available to confirm it: {reason}. Re-run this step inside an agent "
            "chat so a human can approve it, or find an alternative approach."
        )

    if not _parse_interrupt_decision(user_response):
        record_decision(
            tool_name,
            "USER_REJECTED",
            f"User rejected high-risk desktop action: {reason}",
        )
        feedback = _user_rejection_feedback(user_response)
        return (
            f"[BLOCKED] User rejected this action: {reason}."
            + (f" Feedback: {feedback}" if feedback else "")
            + " Please find an alternative approach."
        )

    record_decision(
        tool_name,
        "USER_APPROVED",
        f"User approved high-risk desktop action: {reason}",
    )
    return None


def _is_mutating_activation(action: str) -> bool:
    return action.lower() in _DESKTOP_MUTATING_ACTIONS


def _is_interactive_role(role: str) -> bool:
    """Only activatable controls are gated; static text never is (avoids noise)."""
    return role in INTERACTIVE_AX_ROLES


async def enforce_desktop_interact_guard(
    *,
    ctx: DesktopGuardContext,
    ref_id: str,
    role: str,
    name: str,
    action: str,
    text: str = "",
) -> str | None:
    """Gate AX activation actions on high-risk @dref elements. Returns block message or None."""
    if not _is_mutating_activation(action):
        return None
    if not _is_interactive_role(role):
        return None

    verdict = classify_element_risk(role, name)
    if verdict.level is not SemanticRiskLevel.HIGH:
        return None

    return await _require_hitl_approval(
        ctx=ctx,
        tool_name="desktop_interact_tool",
        reason=verdict.reason,
        tool_input={"action": action, "ref": ref_id, "text": text},
        element={"role": role, "name": name, "ref": ref_id},
    )


def resolve_coordinate_target(
    *,
    scaler: CoordinateScaler,
    refs: Mapping[str, object],
    image_x: int,
    image_y: int,
) -> ElementRef | None:
    """Resolve the interactive element under an image-space coordinate.

    Converts the coordinate to screen space and hit-tests the interactive AX
    bboxes; among overlapping candidates the smallest area wins (the most
    specific control beats its container). Unresolvable coordinates (stale
    refs, empty registry, canvas regions) return None — callers treat None as
    no semantic evidence and leave the action ungated.
    """
    screen_x, screen_y = scaler.api_to_screen(image_x, image_y)
    best: ElementRef | None = None
    best_area = -1
    for value in refs.values():
        if not isinstance(value, ElementRef) or not _is_interactive_role(value.role):
            continue
        bbox = value.bbox
        if (
            bbox.x <= screen_x < bbox.x + bbox.width
            and bbox.y <= screen_y < bbox.y + bbox.height
        ):
            area = bbox.width * bbox.height
            if best is None or area < best_area:
                best = value
                best_area = area
    return best


async def enforce_desktop_vision_guard(
    *,
    ctx: DesktopGuardContext,
    refs: Mapping[str, object],
    action: str,
    coordinate: list[int] | None,
) -> str | None:
    """Gate coordinate-based vision actions on high-risk resolved targets. Returns block message or None."""
    if action not in _VISION_COORDINATE_ACTIONS:
        return None
    if ctx.scaler is None or not refs or coordinate is None or len(coordinate) != 2:
        return None
    assert ctx.scaler is not None

    image_x, image_y = int(coordinate[0]), int(coordinate[1])
    if not ctx.scaler.validate_api_coords(image_x, image_y):
        return None

    target = resolve_coordinate_target(
        scaler=ctx.scaler,
        refs=refs,
        image_x=image_x,
        image_y=image_y,
    )
    if target is None:
        return None

    verdict = classify_element_risk(target.role, target.name)
    if verdict.level is not SemanticRiskLevel.HIGH:
        return None

    return await _require_hitl_approval(
        ctx=ctx,
        tool_name="desktop_vision_tool",
        reason=verdict.reason,
        tool_input={"action": action, "coordinate": [image_x, image_y]},
        element={"role": target.role, "name": target.name, "ref": target.ref_id},
        highlight_screen_xy=(target.bbox.center_x, target.bbox.center_y),
    )
