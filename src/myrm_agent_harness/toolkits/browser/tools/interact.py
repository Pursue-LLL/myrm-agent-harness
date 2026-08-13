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

from .common import mark_untrusted

if TYPE_CHECKING:
    from ..session import BrowserSession

logger = logging.getLogger(__name__)


class InteractStep(BaseModel):
    action: str = Field(
        description="One of: click, dblclick, type, fill, fill_credential, press, hover, focus, "
        "select, scroll, scroll_to_bottom, upload_file, drag, check, uncheck",
    )
    ref: str = Field(description="Element ref from browser_snapshot")
    text: str = Field(
        default="",
        description="Text/key/path as required by the action (drag uses 'x,y' target coordinates)",
    )
    verify_goal: str | None = Field(
        default=None,
        description="Optional visual verification goal for this step",
    )


def _build_interact_input_model(*, labels_str: str) -> type[BaseModel]:
    class InteractInput(BaseModel):
        action: str = Field(
            default="",
            description="Single action when steps is omitted. One of: click, dblclick, type (append keystrokes), "
            "fill (clear then set value), fill_credential (securely fill password/totp), "
            "press, hover, focus, select, scroll, scroll_to_bottom (smart infinite scroll with auto-detection), "
            "upload_file, drag, check (idempotent checkbox on), uncheck (idempotent checkbox off)",
        )
        ref: str = Field(
            default="",
            description="Element ref from browser_snapshot (e.g. 'e0', 'e3', 'f1_e2' for iframe elements). "
            "Required for ref-based mode. Omit when using coordinate mode (x/y).",
        )
        text: str = Field(
            default="",
            description="Text for type/fill, key combo for press (e.g. 'Enter', 'Control+a'), "
            f"credential label for fill_credential (available labels: {labels_str}), "
            "option value(s) for select (multi-select values separated by ';'), "
            "signed scroll delta in pixels for scroll (positive=down, negative=up), "
            "optional params for scroll_to_bottom (e.g. 'max_steps=20,delay_ms=300'), "
            "file path for upload_file, "
            "drag target coordinates 'x,y' (comma-separated CSS pixels, e.g. '500,300'), "
            "or omitted for click/dblclick/hover/focus/check/uncheck.",
        )
        verify_goal: str | None = Field(
            default=None,
            description="Optional. A natural language description of what you expect to see after this action (e.g., 'Flight list is visible', 'Error message disappeared'). If provided, the tool will take screenshots before and after, and use a Vision LLM to verify if the goal was met, returning the visual feedback directly to you.",
        )
        steps: list[InteractStep] | None = Field(
            default=None,
            description="Optional declarative batch: run multiple interact steps in one call (same page, same snapshot refs). "
            "When provided, omit top-level action/ref/text. Each step still runs Semantic Guard.",
        )
        x: float | None = Field(
            default=None,
            description="Viewport X coordinate (CSS pixels) for coordinate mode. "
            "Use when snapshot shows [VISUAL_CONTENT_DETECTED] (canvas/rich-editor pages like Google Docs, Figma). "
            "Identify coordinates from a screenshot. Mutually exclusive with ref.",
        )
        y: float | None = Field(
            default=None,
            description="Viewport Y coordinate (CSS pixels) for coordinate mode. Must be provided together with x.",
        )
        target_x: float | None = Field(
            default=None,
            description="Drag endpoint X coordinate (CSS pixels). Required when action='drag' in coordinate mode.",
        )
        target_y: float | None = Field(
            default=None,
            description="Drag endpoint Y coordinate (CSS pixels). Required when action='drag' in coordinate mode.",
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
                        f"{result}\nFile downloaded: {latest.file_name} ({latest.file_size} bytes)\n"
                        f"Path: {latest.path}"
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

        Two modes (mutually exclusive):
        1. Ref mode: browser_snapshot -> pick ref -> browser_interact(action, ref).
        2. Coordinate mode: screenshot -> identify position -> browser_interact(action, x=..., y=...).
           Use coordinate mode when snapshot shows [VISUAL_CONTENT_DETECTED] (canvas/rich-editor).

        Works across iframes (refs like 'f1_e2' target iframe elements).
        Use steps[] to batch multiple ref-based actions without extra LLM rounds.
        If click triggers a file download, it's auto-captured; use list_downloads to check.
        Use verify_goal to automatically verify the visual result of your action.
        """
        # Coordinate mode
        if x is not None and y is not None:
            if ref.strip():
                return "Error: ref and x/y are mutually exclusive. Use ref OR coordinates, not both."
            if not action.strip():
                return "Error: action is required for coordinate mode"
            return mark_untrusted(
                await session.interact_at(
                    action=action, x=x, y=y, text=text,
                    target_x=target_x, target_y=target_y,
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
            for index, step in enumerate(steps, start=1):
                step_result = await _run_single(step.action, step.ref, step.text, step.verify_goal)
                lines.append(f"Step {index} ({step.action} {step.ref}): {step_result}")
            return mark_untrusted("\n".join(lines))

        # Ref mode
        if not action.strip():
            return "Error: action is required when steps is omitted"
        if not ref.strip():
            return "Error: ref is required when steps is omitted (or use x/y for coordinate mode)"

        return mark_untrusted(await _run_single(action, ref, text, verify_goal))

    return browser_interact
