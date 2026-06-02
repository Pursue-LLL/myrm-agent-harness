"""Browser console log capture for Agent diagnostics.

Captures JS console messages (log/warn/error) and page errors, providing
the Agent with visibility into client-side issues without manual user intervention.

[INPUT]
- patchright.async_api::Page (POS: Playwright page instance)
- patchright.async_api::ConsoleMessage (POS: Playwright console message)

[OUTPUT]
- ConsoleEntry: Immutable console message record
- ConsoleLogger: Synchronous console capture and formatting

[POS]
Console log capture for the browser toolkit. Mirrors NetworkLogger's lifecycle
management pattern (attach/detach per page, FIFO bounded buffer).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import ConsoleMessage, Error, Page

logger = logging.getLogger(__name__)

_ERROR_TYPES = frozenset({"error", "warning"})
_MAX_TEXT_LENGTH = 500


@dataclass(frozen=True, slots=True)
class ConsoleEntry:
    """Immutable record of a browser console message."""

    level: str
    text: str
    url: str
    timestamp: float

    @property
    def is_error(self) -> bool:
        return self.level in _ERROR_TYPES


class ConsoleLogger:
    """Captures browser console output for Agent diagnostics.

    Uses bounded FIFO deque to prevent unbounded memory growth.
    Lifecycle managed by BrowserSession (attach on tab switch, detach on close).
    """

    def __init__(self, max_entries: int = 100) -> None:
        self._entries: deque[ConsoleEntry] = deque(maxlen=max_entries)
        self._bound_page: Page | None = None

    def _cb_console(self, msg: ConsoleMessage) -> None:
        try:
            text = msg.text[:_MAX_TEXT_LENGTH]
            location = msg.location
            url = f"{location.get('url', '')}:{location.get('lineNumber', '')}" if location else ""
            self._entries.append(
                ConsoleEntry(
                    level=msg.type,
                    text=text,
                    url=url,
                    timestamp=time.time(),
                )
            )
        except Exception as exc:
            logger.warning("ConsoleLogger: failed to capture message: %s", exc)

    def _cb_pageerror(self, error: Error) -> None:
        try:
            text = str(error)[:_MAX_TEXT_LENGTH]
            self._entries.append(
                ConsoleEntry(
                    level="error",
                    text=f"[PageError] {text}",
                    url="",
                    timestamp=time.time(),
                )
            )
        except Exception as exc:
            logger.warning("ConsoleLogger: failed to capture page error: %s", exc)

    def start_capture(self, page: Page) -> None:
        """Register console listeners on page. Idempotent for same page."""
        if self._bound_page is page:
            return
        if self._bound_page is not None:
            self.detach_current()
        self._bound_page = page
        page.on("console", self._cb_console)
        page.on("pageerror", self._cb_pageerror)

    def detach_page(self, page: Page) -> None:
        """Remove listeners from a specific page."""
        if self._bound_page is not page:
            return
        try:
            page.off("console", self._cb_console)
            page.off("pageerror", self._cb_pageerror)
        except Exception as exc:
            logger.warning("ConsoleLogger: detach failed: %s", exc)
        finally:
            if self._bound_page is page:
                self._bound_page = None

    def detach_current(self) -> None:
        """Detach from currently bound page."""
        if self._bound_page is not None:
            self.detach_page(self._bound_page)

    def stop_capture(self) -> None:
        """Detach and clear pending state (preserves existing entries)."""
        self.detach_current()

    def get_summary(self, errors_only: bool = False) -> str:
        """Format captured console entries for the Agent.

        Args:
            errors_only: If True, only return error/warning messages.

        Returns:
            Formatted string of console messages, or "No console messages" if empty.
        """
        entries = [e for e in self._entries if not errors_only or e.is_error]
        if not entries:
            return "No console messages captured." if not errors_only else "No console errors."

        lines: list[str] = []
        for entry in entries[-30:]:
            prefix = f"[{entry.level.upper()}]"
            loc = f" ({entry.url})" if entry.url else ""
            lines.append(f"{prefix} {entry.text}{loc}")

        total = len(entries)
        shown = min(total, 30)
        header = f"Console log ({shown}/{total} entries"
        if errors_only:
            header += ", errors only"
        header += "):"
        return header + "\n" + "\n".join(lines)
