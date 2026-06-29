"""BBox fallback click when AX invoke fails."""

from __future__ import annotations

from myrm_agent_harness.toolkits.computer_use.types import ActionResult, ModifierKey
from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef


async def try_bbox_click(
    session: object,
    element: ElementRef,
    action: str,
    text: str,
    modifiers: list[ModifierKey] | None,
) -> ActionResult:
    backend = session._backend  # type: ignore[attr-defined]
    normalized = action.lower()
    x = element.bbox.center_x
    y = element.bbox.center_y

    if normalized in {"fill", "type"}:
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
