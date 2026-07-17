"""BBox fallback click when AX invoke fails.

This is the coordinate-based fallback path — it WILL steal foreground focus
(pyautogui/xdotool moves the real cursor). The foreground permission gate
must be checked before entering this function.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.computer_use.types import ActionResult, ModifierKey
from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.computer_use.session import ComputerSession


async def try_bbox_click(
    session: ComputerSession,
    element: ElementRef,
    action: str,
    text: str,
    modifiers: list[ModifierKey] | None,
) -> ActionResult:
    meta = getattr(getattr(session, "_refs", None), "meta", None)
    app_name = meta.app_name if meta else ""
    window_title = meta.window_title if meta else ""
    permission_denied = await session.check_foreground_permission(
        reason=f"AX invoke failed for @{element.ref_id}; falling back to coordinate click",
        operation=f"bbox_click({element.bbox.center_x}, {element.bbox.center_y})",
        estimated_duration_seconds=3.0,
        app_name=app_name,
        window_title=window_title,
    )
    if permission_denied is not None:
        return permission_denied

    backend = session._backend  # type: ignore[attr-defined]
    normalized = action.lower()
    x = element.bbox.center_x
    y = element.bbox.center_y

    if normalized in {"fill", "type", "set_value"}:
        click_result = await backend.click(x, y, modifiers=modifiers)
        if not click_result.success:
            return click_result
        if not text:
            return ActionResult(success=True, output="Focused element via bbox click")
        return await backend.type_text(text)

    if normalized in {"click", "press", "hover", "focus", "dblclick", "double_click"}:
        clicks = 2 if normalized in {"dblclick", "double_click"} else 1
        return await backend.click(x, y, clicks=clicks, modifiers=modifiers)

    return ActionResult(success=False, error=f"BBox fallback unsupported for action: {action}")
