"""Viewport, dialog, and misc page-level helpers for BrowserSession.

[INPUT]
- session.extractor::_PDF_HEADER_TEMPLATE, _PDF_FOOTER_TEMPLATE, _PDF_MARGIN (POS: PDF metadata templates)

[OUTPUT]
- BrowserSessionPageMixin: evaluate, navigation helpers, PDF to temp path, viewport,...

[POS]
Viewport, dialog, and misc page-level helpers for BrowserSession.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.browser.session.extractor import (
    _PDF_FOOTER_TEMPLATE,
    _PDF_HEADER_TEMPLATE,
    _PDF_MARGIN,
)

logger = logging.getLogger(__name__)


class BrowserSessionPageMixin:
    """evaluate, navigation helpers, PDF to temp path, viewport, load state, dialogs."""

    async def evaluate(self, expression: str) -> str:
        """Execute JavaScript code"""
        await self._ensure_components()

        from myrm_agent_harness.toolkits.browser.tools.semantic_dom_hitl import enforce_js_eval_guard

        blocked = await enforce_js_eval_guard(
            session=self,
            tool_name="browser_manage_tool",
            expression=expression,
        )
        if blocked is not None:
            return blocked

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

    async def save_pdf(self, *, include_metadata: bool = True) -> str:
        """Export current page as PDF with metadata header/footer and background."""
        await self._ensure_components()
        page = self._tab_controller.get_active_page()

        pdf_path = Path(tempfile.gettempdir()) / f"page_{self.get_active_tab_id()}.pdf"
        if include_metadata:
            await page.pdf(
                path=str(pdf_path),
                print_background=True,
                display_header_footer=True,
                header_template=_PDF_HEADER_TEMPLATE,
                footer_template=_PDF_FOOTER_TEMPLATE,
                margin=_PDF_MARGIN,
            )
        else:
            await page.pdf(path=str(pdf_path), print_background=True)
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
