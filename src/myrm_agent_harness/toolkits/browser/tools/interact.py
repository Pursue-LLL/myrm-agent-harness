"""browser_interact tool for element interactions.

[INPUT]
- common::mark_untrusted (POS: unified browser output security boundary; credential redaction + untrusted-content wrapping)
- session.browser_session::BrowserSession (POS: browser session aggregate root; semantic guard in interact)

[OUTPUT]
- create_interact_tool: Create browser_interact tool bound to session.

[POS]
browser_interact tool for element interactions. Two modes: ref-based (via BrowserSession.interact
with Semantic DOM HITL) and coordinate-based (via BrowserSession.interact_at for canvas/rich-editor
pages). This tool adds download detection for ref-based click/dblclick.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

from ..exceptions import RefNotFoundError
from .common import mark_untrusted

if TYPE_CHECKING:
    from ..session import BrowserSession

logger = logging.getLogger(__name__)


class InteractStep(BaseModel):
    action: str = Field(
        description="One of: click, dblclick, type, fill, fill_credential, press, hover, focus, "
        "select, scroll, scroll_to_bottom, upload_file, drag, check, uncheck",
    )
    ref: str = Field(description="Element ref from browser_snapshot (e.g. 'e0', 'f1_e2')")
    text: str = Field(
        default="",
        description="Text/key/path as required by the action (drag uses 'x,y' target coordinates)",
    )
    verify_goal: str | None = Field(
        default=None,
        description="Optional visual verification goal for this step (e.g. 'Dropdown opened', 'Form filled')",
    )


def _build_interact_input_model(*, labels_str: str) -> type[BaseModel]:
    class InteractInput(BaseModel):
        action: str = Field(
            default="",
            description="Single action when steps is omitted. One of: click, dblclick, "
            "type (append keystrokes to element), "
            "fill (clear element then set exact value), "
            "fill_credential (securely fill password/totp from vault), "
            "press (send key combo like 'Enter', 'Escape', 'Control+a'), "
            "hover, focus, "
            "select (select dropdown option by value), "
            "scroll (scroll page/element by pixel delta, positive=down, negative=up), "
            "scroll_to_bottom (smart infinite scroll until content stabilizes), "
            "upload_file (upload file from local path), "
            "drag (drag element to target coordinates), "
            "check (idempotently check checkbox), "
            "uncheck (idempotently uncheck checkbox)",
        )
        ref: str = Field(
            default="",
            description="Element ref from browser_snapshot (e.g. 'e0', 'e3', 'f1_e2' for iframe elements). "
            "Required for Ref mode. Do NOT provide when using Coordinate mode (x/y).",
        )
        text: str = Field(
            default="",
            description="Argument required by the selected action: "
            "text for type/fill; "
            "key combo for press (e.g. 'Enter', 'Control+a'); "
            f"credential label for fill_credential (available labels: {labels_str}); "
            "option value(s) for select (separate multiple with ';'); "
            "pixel delta for scroll (e.g. '500' for down, '-300' for up); "
            "optional parameters for scroll_to_bottom (e.g. 'max_steps=20,delay_ms=300'); "
            "absolute file path for upload_file; "
            "target 'x,y' CSS coordinates for drag (e.g. '500,300'); "
            "leave empty for click/dblclick/hover/focus/check/uncheck.",
        )
        verify_goal: str | None = Field(
            default=None,
            description="Optional natural language description of expected visual outcome (e.g. 'Results list visible', 'Modal closed'). Automatically verifies visual result and returns feedback.",
        )
        steps: list[InteractStep] | None = Field(
            default=None,
            description="Optional declarative batch: execute multiple interact steps sequentially in one tool call (using same page and snapshot refs). When provided, omit top-level action/ref/text.",
        )
        x: float | None = Field(
            default=None,
            description="Viewport X coordinate (CSS pixels) for Coordinate mode. "
            "Use when snapshot indicates [VISUAL_CONTENT_DETECTED] (canvas/rich-editor like Google Docs, Figma). "
            "Must be provided together with y. Mutually exclusive with ref.",
        )
        y: float | None = Field(
            default=None,
            description="Viewport Y coordinate (CSS pixels) for Coordinate mode. Must be provided together with x.",
        )
        target_x: float | None = Field(
            default=None,
            description="Drag endpoint X coordinate (CSS pixels). Required when action='drag' in Coordinate mode.",
        )
        target_y: float | None = Field(
            default=None,
            description="Drag endpoint Y coordinate (CSS pixels). Required when action='drag' in Coordinate mode.",
        )

    return InteractInput


def create_interact_tool(session: BrowserSession):
    """Create browser_interact tool bound to session."""

    from myrm_agent_harness.core.security.credential_vault import get_global_credential_vault

    vault = get_global_credential_vault()
    labels = vault.list_labels()
    labels_str = ", ".join([f"'{lbl}'" for lbl in labels]) if labels else "none available"
    InteractInput = _build_interact_input_model(labels_str=labels_str)  # noqa: N806  # dynamically built model class

    async def _run_single(action: str, ref: str, text: str, verify_goal: str | None) -> str:
        count_before = len(session.list_downloads())
        result = await session.interact(action, ref, text, verify_goal=verify_goal)

        if action in ("click", "dblclick") and session.download_enabled:
            await asyncio.sleep(0.5)
            if len(session.list_downloads()) > count_before:
                latest = session.last_download
                if latest:
                    result = (
                        f"{result}\nFile downloaded: {latest.file_name} ({latest.file_size} bytes)\nPath: {latest.path}"
                    )
        return result

    @tool("browser_interact_tool", args_schema=InteractInput)
    async def browser_interact(
        action: str = "",
        ref: str = "",
        text: str = "",
        verify_goal: str | None = None,
        steps: list[InteractStep] | None = None,
        x: float | None = None,
        y: float | None = None,
        target_x: float | None = None,
        target_y: float | None = None,
    ) -> str:
        """Perform an action on a page element identified by its ref ID or viewport coordinates.

        Supports two mutually exclusive interaction modes:
        1. Ref mode: Call browser_snapshot_tool -> get element ref (e.g. 'e0', 'f1_e2') -> browser_interact(action=..., ref=...).
        2. Coordinate mode: Use when snapshot indicates [VISUAL_CONTENT_DETECTED] (canvas/rich-editor) -> browser_interact(action=..., x=..., y=...).

        Features:
        - Works seamlessly across iframes (use refs like 'f1_e2').
        - Use steps=[] to batch multiple sequential actions in a single turn without extra round-trips.
        - File downloads triggered by click are automatically tracked.
        - Set verify_goal to visually verify the action's outcome.
        """
        # Coordinate mode
        if x is not None and y is not None:
            if ref.strip():
                return "Error: ref and x/y are mutually exclusive. Use ref OR coordinates, not both."
            if not action.strip():
                return "Error: action is required for coordinate mode"
            return mark_untrusted(
                await session.interact_at(
                    action=action,
                    x=x,
                    y=y,
                    text=text,
                    target_x=target_x,
                    target_y=target_y,
                    verify_goal=verify_goal,
                )
            )
        if (x is not None) != (y is not None):
            return "Error: both x and y must be provided together for coordinate mode"

        # Batch mode
        if steps is not None:
            if len(steps) == 0:
                return "Error: steps must contain at least one action when batch mode is used"
            lines: list[str] = []
            page = session.get_active_page()
            for index, step in enumerate(steps, start=1):
                url_before = page.url if page else ""
                step_result = await _run_single(step.action, step.ref, step.text, step.verify_goal)
                lines.append(f"Step {index} ({step.action} {step.ref}): {step_result}")

                # Post-action navigation guard: halt subsequent steps if page navigated
                url_after = page.url if page else ""
                if url_before and url_after and index < len(steps):
                    change_type, _, _ = RefNotFoundError._classify_url_change(url_before, url_after)
                    if change_type == "path":
                        remaining_count = len(steps) - index
                        lines.append(
                            f"[NAVIGATION_HALTED: Step {index} triggered navigation to '{url_after}'. "
                            f"Remaining {remaining_count} steps halted to prevent stale element execution. "
                            "Call browser_snapshot to get fresh refs for the new page.]"
                        )
                        break

            return mark_untrusted("\n".join(lines))

        # Ref mode
        if not action.strip():
            return "Error: action is required when steps is omitted"
        if not ref.strip():
            return "Error: ref is required when steps is omitted (or use x/y for coordinate mode)"

        return mark_untrusted(await _run_single(action, ref, text, verify_goal))

    return browser_interact
