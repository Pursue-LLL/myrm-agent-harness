"""Bézier-mouse click behaviors for the Interactor.

[INPUT]
- pool.config::HumanizeConfig (POS: interaction humanization config)
- exceptions::ClickTargetUnreachableError (POS: interaction target cannot be brought into view)
- session.humanize::bezier_move, click_delay (POS: humanized delay and Bézier mouse helpers)
- session.interactor_scroll_targeting_mixin::ScrollTargetingMixin (POS: CAREFUL pre-interaction target centering)

[OUTPUT]
- ClickInteractMixin: click with Bézier mouse trajectory + reachability guard
  against silent edge clicks (CAREFUL mode)

[POS]
CAREFUL-mode click behaviors mixed into Interactor. Moves the mouse to a target
along a Bézier curve, refuses native clicks that would only silently miss
(off-viewport target with no wheel-scrollable path), and otherwise clicks via
low-level mouse API so the humanized trajectory survives. Depends on the
rendered-state probe of ScrollTargetingMixin; mixed into Interactor after it.
"""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.browser.exceptions import (
    ClickTargetUnreachableError,
)
from myrm_agent_harness.toolkits.browser.session.humanize import (
    INTERACTION_TIMEOUT_MS,
    bezier_move,
    click_delay,
)

if TYPE_CHECKING:
    from patchright.async_api import Locator


class ClickInteractMixin:
    """Bézier-mouse click trajectory with a reachability guard (CAREFUL mode)."""

    async def _bezier_move_to(self, locator: Locator) -> bool:
        """Move mouse to the locator via Bézier curve. Returns True if move succeeded."""
        # "attached" not "visible": patchright's visible semantics reject elements
        # clipped by an iframe viewport even after they were scrolled into it, and
        # the off-viewport check below is the real reachability gate anyway.
        await locator.wait_for(state="attached", timeout=INTERACTION_TIMEOUT_MS)
        box = await locator.bounding_box(timeout=INTERACTION_TIMEOUT_MS)
        if box is None:
            return False

        target_x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
        target_y = box["y"] + box["height"] * random.uniform(0.35, 0.65)

        viewport = self._page.viewport_size or {"width": 1280, "height": 720}
        vw, vh = float(viewport["width"]), float(viewport["height"])
        # CDP clamps off-viewport mouse coordinates to the viewport edge, so moving
        # to a target whose center is still outside the viewport would make the
        # mouse.down/up land on the edge and miss silently. Hand the interaction back
        # to the native locator action instead: its scrollIntoViewIfNeeded either
        # scrolls the target in, or fails loudly — never a silent wrong click.
        if not (0.0 <= target_x <= vw and 0.0 <= target_y <= vh):
            return False

        if self._mouse_x == 0.0 and self._mouse_y == 0.0:
            self._mouse_x = vw / 2
            self._mouse_y = vh / 2

        await bezier_move(
            self._page, self._mouse_x, self._mouse_y, target_x, target_y, self._humanize
        )
        self._mouse_x, self._mouse_y = target_x, target_y
        return True

    async def _guard_native_click(self, locator: Locator) -> None:
        """Refuse a native click that could only silently miss.

        After the humanized pre-scroll, an off-viewport target with no
        wheel-scrollable ancestor (e.g. body overflow:hidden) cannot be brought
        in — the native locator.click would clamp the pointer to the viewport
        edge and report success while hitting nothing. Fail loudly instead.
        Targets with a scroll path, or targets the probe cannot measure, still
        fall through to the native click (its scrollIntoViewIfNeeded can help).
        """
        probe = await self._target_probe(locator)
        if probe is None:
            return
        if not probe["visible"] and not probe.get("container"):
            raise ClickTargetUnreachableError(
                "Click target is outside the viewport and no scrollable "
                "container exists to bring it in (locked scroll). Refusing to "
                "click at the viewport edge."
            )

    async def _bezier_click(self, locator: Locator, ref: str, healed_msg: str) -> str:
        """Click with Bézier mouse trajectory (CAREFUL mode only).

        Uses low-level mouse API to preserve the Bézier path that locator.click()
        would overwrite with an instantaneous move.
        """
        if not await self._bezier_move_to(locator):
            await self._guard_native_click(locator)
            delay = click_delay(self._humanize)
            await locator.click(delay=delay, timeout=INTERACTION_TIMEOUT_MS)
            return f"Clicked {ref}{healed_msg}"

        delay_ms = click_delay(self._humanize)
        await self._page.mouse.down()
        await asyncio.sleep(delay_ms / 1000.0)
        await self._page.mouse.up()

        return f"Clicked {ref}{healed_msg}"
