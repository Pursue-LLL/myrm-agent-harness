"""Viewport, dialog, and misc page-level helpers for BrowserSession.

[INPUT]
- (none)

[OUTPUT]
- BrowserSessionPageMixin: evaluate, navigation helpers, PDF to temp path, viewport,...

[POS]
Viewport, dialog, and misc page-level helpers for BrowserSession.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class BrowserSessionPageMixin:
    """evaluate, navigation helpers, PDF to temp path, viewport, load state, dialogs."""

    async def evaluate(self, expression: str) -> str:
        """Execute JavaScript code"""
        await self._ensure_components()
        page = self._tab_controller.get_active_page()

        result = await page.evaluate(expression)
        logger.info("BrowserSession: evaluated JS expression")
        return str(result)

    async def go_back(self) -> str:
        """Go back one page"""
        await self._ensure_components()
        navigator = self._require_navigator()

        await navigator.back()
        return "Navigated back"

    async def go_forward(self) -> str:
        """Go forward one page"""
        await self._ensure_components()
        navigator = self._require_navigator()

        await navigator.forward()
        return "Navigated forward"

    async def save_pdf(self) -> str:
        """Export PDF (Base64)"""
        await self._ensure_components()
        page = self._tab_controller.get_active_page()

        pdf_path = Path(tempfile.gettempdir()) / f"page_{self.get_active_tab_id()}.pdf"
        await page.pdf(path=str(pdf_path))
        logger.info("BrowserSession: saved PDF to %s", pdf_path)
        return f"Saved PDF to {pdf_path}"

    async def resize(self, width: int, height: int) -> str:
        """Resize viewport"""
        await self._ensure_components()
        page = self._tab_controller.get_active_page()

        await page.set_viewport_size({"width": width, "height": height})
        logger.info("BrowserSession: resized viewport to %dx%d", width, height)
        return f"Resized viewport to {width}x{height}"

    async def wait_for_load(self) -> str:
        """Wait for page load completion"""
        await self._ensure_components()
        page = self._tab_controller.get_active_page()

        await page.wait_for_load_state("networkidle", timeout=10_000)
        logger.info("BrowserSession: page load completed")
        return "Page load completed"

    async def set_dialog_response(self, accept: bool, prompt_text: str = "") -> str:
        """Respond to a pending dialog (WAIT_FOR_AGENT mode) or confirm action.

        In WAIT_FOR_AGENT mode: responds to the currently pending dialog.
        In other modes: logs intent (dialogs are already handled automatically).
        """
        await self._ensure_components()
        return await self._dialog_manager.respond(accept, prompt_text)
