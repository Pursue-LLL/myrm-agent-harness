"""Coordinate-based (Visual Mode) interactions for the Interactor.

[INPUT]
- pool.config::HumanizeConfig (POS: interaction humanization config)
- session.humanize::bezier_move, click_delay, type_delay (POS: humanized delay, Bézier mouse, and wheel-burst scroll helpers)
- session.interactor_scroll_mixin::ScrollHumanizeMixin (POS: humanized wheel-input scrolling behaviors)

[OUTPUT]
- CoordInteractMixin: coordinate-based interaction manager — click/dblclick/type/
  press/hover/scroll/drag at explicit viewport coordinates for canvas/rich-editor pages

[POS]
Coordinate interaction behaviors mixed into Interactor. Executes 7 actions at
viewport positions (click/dblclick/type/press/hover/scroll/drag) with the same
humanization stack as ref interactions (Gaussian delays, Bézier trajectory in
CAREFUL mode) and viewport-bounds validation before any dispatch. Used for
canvas/rich-editor pages (Google Docs, Figma, Sheets) where DOM refs do not map
to visible elements.
"""

from __future__ import annotations

import asyncio
import logging

from myrm_agent_harness.toolkits.browser.session.humanize import (
    bezier_move,
    click_delay,
    type_delay,
)

logger = logging.getLogger(__name__)


class CoordInteractMixin:
    """Coordinate-based interaction — Visual Mode actions at viewport positions."""

    _COORD_ACTIONS = frozenset(
        {"click", "dblclick", "type", "press", "hover", "scroll", "drag"}
    )

    async def interact_at(
        self,
        action: str,
        x: float,
        y: float,
        text: str = "",
        target_x: float | None = None,
        target_y: float | None = None,
    ) -> str:
        """Execute a coordinate-based interaction at viewport position (x, y).

        Used for canvas/rich-editor pages (Google Docs, Figma, Sheets) where
        DOM refs do not map to visible elements.

        Args:
            action: One of click/dblclick/type/press/hover/scroll/drag.
            x: Viewport X coordinate (CSS pixels).
            y: Viewport Y coordinate (CSS pixels).
            text: Text for type, key combo for press, signed pixel delta for scroll.
            target_x: Drag endpoint X (required when action='drag').
            target_y: Drag endpoint Y (required when action='drag').

        Returns:
            Description of the interaction result.

        Raises:
            ValueError: If action is unsupported or coordinates are out of bounds.
        """
        if action not in self._COORD_ACTIONS:
            raise ValueError(
                f"Invalid coordinate action: {action}. "
                f"Supported: {sorted(self._COORD_ACTIONS)}"
            )

        viewport = self._page.viewport_size or {"width": 1280, "height": 720}
        vw, vh = viewport["width"], viewport["height"]
        if not (0 <= x <= vw and 0 <= y <= vh):
            raise ValueError(
                f"Coordinates ({x}, {y}) out of viewport bounds ({vw}×{vh}). "
                "Use coordinates within the visible viewport area."
            )

        from myrm_agent_harness.toolkits.browser.wait import (
            WaitStrategy,
            wait_for_page_ready,
        )

        async def _wait_after() -> None:
            try:
                await wait_for_page_ready(
                    self._page, strategy=WaitStrategy.SPA_STABLE, max_ms=3000
                )
            except Exception as exc:
                logger.debug("Interactor: post-coord-action SPA wait failed: %s", exc)

        if action == "click":
            if self._humanize.enable_bezier_mouse:
                await bezier_move(
                    self._page, self._mouse_x, self._mouse_y, x, y, self._humanize
                )
            else:
                await self._page.mouse.move(x, y)
            delay_ms = click_delay(self._humanize)
            await self._page.mouse.down()
            await asyncio.sleep(delay_ms / 1000.0)
            await self._page.mouse.up()
            self._mouse_x, self._mouse_y = x, y
            await _wait_after()
            return f"Clicked at ({x}, {y})"

        if action == "dblclick":
            await self._page.mouse.dblclick(x, y)
            self._mouse_x, self._mouse_y = x, y
            await _wait_after()
            return f"Double-clicked at ({x}, {y})"

        if action == "type":
            if not text:
                raise ValueError("'text' is required for type action")
            if self._humanize.enable_bezier_mouse:
                await bezier_move(
                    self._page, self._mouse_x, self._mouse_y, x, y, self._humanize
                )
            else:
                await self._page.mouse.move(x, y)
            await self._page.mouse.click(x, y)
            self._mouse_x, self._mouse_y = x, y
            delay_per_char = type_delay(self._humanize)
            await self._page.keyboard.type(text, delay=delay_per_char)
            await _wait_after()
            return f"Typed '{text}' at ({x}, {y})"

        if action == "press":
            if not text:
                raise ValueError("'text' (key combo) is required for press action")
            await self._page.mouse.click(x, y)
            self._mouse_x, self._mouse_y = x, y
            await self._page.keyboard.press(text)
            await _wait_after()
            return f"Pressed '{text}' at ({x}, {y})"

        if action == "hover":
            if self._humanize.enable_bezier_mouse:
                await bezier_move(
                    self._page, self._mouse_x, self._mouse_y, x, y, self._humanize
                )
            else:
                await self._page.mouse.move(x, y)
            self._mouse_x, self._mouse_y = x, y
            return f"Hovered at ({x}, {y})"

        if action == "scroll":
            if not text:
                raise ValueError(
                    "'text' (signed pixel delta) is required for scroll action"
                )
            try:
                delta = int(text)
            except ValueError as exc:
                raise ValueError(
                    f"Scroll requires numeric text (pixel delta), got: {text}"
                ) from exc
            await self._page.mouse.move(x, y)
            self._mouse_x, self._mouse_y = x, y
            return await self._scroll_with_report(x, y, delta, f" at ({x}, {y})")

        if action == "drag":
            if target_x is None or target_y is None:
                raise ValueError(
                    "'target_x' and 'target_y' are required for drag action"
                )
            if not (0 <= target_x <= vw and 0 <= target_y <= vh):
                raise ValueError(
                    f"Drag target ({target_x}, {target_y}) out of viewport bounds ({vw}×{vh})."
                )
            if self._humanize.enable_bezier_mouse:
                await bezier_move(
                    self._page, self._mouse_x, self._mouse_y, x, y, self._humanize
                )
            else:
                await self._page.mouse.move(x, y)
            await self._page.mouse.down()
            if self._humanize.enable_bezier_mouse:
                await bezier_move(self._page, x, y, target_x, target_y, self._humanize)
            else:
                await self._page.mouse.move(target_x, target_y, steps=10)
            await self._page.mouse.up()
            self._mouse_x, self._mouse_y = target_x, target_y
            await _wait_after()
            return f"Dragged from ({x}, {y}) to ({target_x}, {target_y})"

        return f"Unknown coordinate action: {action}"
