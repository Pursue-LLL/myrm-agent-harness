"""BBox fallback click when AX invoke fails.

This is the coordinate-based fallback path. On macOS, when the snapshot meta
carries the target app pid, input is routed directly to that process and the
foreground guard aborts on focus leaks — the real cursor never moves. Other
platforms (and pid-less snapshots) keep the legacy foreground behavior. The
foreground permission gate must be checked before entering this function.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.computer_use.backends.protocols import (
    ComputerBackend,
)
from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef
from myrm_agent_harness.toolkits.computer_use.types import ActionResult, ModifierKey

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

    backend = session._backend
    normalized = action.lower()
    x = element.bbox.center_x
    y = element.bbox.center_y

    if normalized not in {
        "fill",
        "type",
        "set_value",
        "click",
        "press",
        "hover",
        "focus",
        "dblclick",
        "double_click",
    }:
        return ActionResult(
            success=False, error=f"BBox fallback unsupported for action: {action}"
        )

    target_pid = meta.pid if meta and meta.pid else None
    if type(backend).__name__ == "MacOSBackend" and target_pid:
        from myrm_agent_harness.toolkits.computer_use.backends import macos_input
        from myrm_agent_harness.toolkits.computer_use.backends.macos_background import (
            ensure_post_event_access,
            guard_foreground,
        )
        from myrm_agent_harness.toolkits.computer_use.dref.errors import (
            FocusChangedError,
        )

        if not ensure_post_event_access():
            return ActionResult(
                success=False,
                error=(
                    "macOS denied event posting for background input. "
                    "Grant access when prompted, then retry the same call; "
                    "or snapshot with scope='foreground' to act in the frontmost app."
                ),
            )
        macos_input.set_input_target(target_pid)
        try:
            with guard_foreground():
                return await _run_bbox_action(
                    backend, normalized, x, y, text, modifiers
                )
        except FocusChangedError as exc:
            return ActionResult(success=False, error=str(exc))
        finally:
            macos_input.clear_input_target()
    return await _run_bbox_action(backend, normalized, x, y, text, modifiers)


async def _run_bbox_action(
    backend: ComputerBackend,
    normalized: str,
    x: int,
    y: int,
    text: str,
    modifiers: list[ModifierKey] | None,
) -> ActionResult:
    """Execute one bbox coordinate action against the backend."""
    if normalized in {"fill", "type", "set_value"}:
        click_result = await backend.click(x, y, modifiers=modifiers)
        if not click_result.success:
            return click_result
        if not text:
            return ActionResult(success=True, output="Focused element via bbox click")
        return await backend.type_text(text)

    clicks = 2 if normalized in {"dblclick", "double_click"} else 1
    return await backend.click(x, y, clicks=clicks, modifiers=modifiers)
