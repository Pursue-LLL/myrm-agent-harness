"""Dialog lifecycle manager for BrowserSession.

[INPUT]
- (none)

[OUTPUT]
- DialogPolicy: enum of dialog handling strategies
- DialogRecord: immutable record of a handled dialog
- DialogManager: single-responsibility component for automatic dialog handling

[POS]
Manages JavaScript dialog events (alert/confirm/prompt/beforeunload) on a page.
Registers a handler at page creation time, processes dialogs according to the
configured policy, and maintains a bounded history for Agent visibility.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Dialog, Page

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 60.0
_MAX_RECENT = 10
_MAX_PENDING = 5


class DialogPolicy(str, Enum):
    """Dialog handling strategy.

    SMART: alert/confirm/beforeunload→accept, prompt→dismiss (safest default)
    AUTO_ACCEPT: accept all dialogs unconditionally
    AUTO_DISMISS: dismiss all dialogs unconditionally
    WAIT_FOR_AGENT: pause and wait for Agent to respond via dialog_response action
    """

    SMART = "smart"
    AUTO_ACCEPT = "auto_accept"
    AUTO_DISMISS = "auto_dismiss"
    WAIT_FOR_AGENT = "wait_for_agent"


@dataclass(frozen=True)
class DialogRecord:
    """Immutable record of a dialog that was intercepted and handled."""

    dialog_type: str
    message: str
    default_value: str
    timestamp: float
    action_taken: str  # "accepted" | "dismissed"
    handled_by: str  # "smart" | "auto_accept" | "auto_dismiss" | "agent" | "timeout"


class DialogManager:
    """Manages JS dialog interception for a BrowserSession page.

    Lifecycle:
        1. Constructed with a policy
        2. attach(page) registers the handler (idempotent)
        3. Handler fires on dialog event, processes per policy
        4. get_recent() returns bounded history for snapshot visibility
        5. respond() allows Agent to handle pending dialog in WAIT_FOR_AGENT mode
    """

    def __init__(
        self,
        policy: DialogPolicy = DialogPolicy.SMART,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._policy = policy
        self._timeout_s = timeout_s
        self._recent: deque[DialogRecord] = deque(maxlen=_MAX_RECENT)
        self._pending: deque[_PendingDialog] = deque(maxlen=_MAX_PENDING)
        self._attached_pages: set[int] = set()

    @property
    def policy(self) -> DialogPolicy:
        return self._policy

    def attach(self, page: Page) -> None:
        """Register dialog handler on page. Idempotent per page instance."""
        page_id = id(page)
        if page_id in self._attached_pages:
            return
        self._attached_pages.add(page_id)
        page.on("dialog", self._handle_dialog)
        logger.debug("DialogManager: attached to page %d (policy=%s)", page_id, self._policy.value)

    def detach(self, page: Page) -> None:
        """Remove dialog handler from page."""
        page_id = id(page)
        self._attached_pages.discard(page_id)
        page.remove_listener("dialog", self._handle_dialog)

    def get_recent(self) -> list[DialogRecord]:
        """Get recent dialog records (for snapshot visibility)."""
        return list(self._recent)

    def get_pending(self) -> list[DialogRecord]:
        """Get pending dialogs awaiting Agent response (WAIT_FOR_AGENT mode)."""
        return [
            DialogRecord(
                dialog_type=p.dialog_type,
                message=p.message,
                default_value=p.default_value,
                timestamp=p.timestamp,
                action_taken="pending",
                handled_by="awaiting_agent",
            )
            for p in self._pending
            if not p.resolved.is_set()
        ]

    def clear_recent(self) -> None:
        """Clear recent dialogs after they've been reported."""
        self._recent.clear()

    async def respond(self, accept: bool, prompt_text: str = "") -> str:
        """Respond to a pending dialog (WAIT_FOR_AGENT mode).

        Returns a status message.
        """
        if not self._pending:
            return "No pending dialog to respond to."

        pending = self._pending[0]
        if pending.resolved.is_set():
            self._pending.popleft()
            return "Dialog was already handled (timeout)."

        pending.accept = accept
        pending.prompt_text = prompt_text
        pending.resolved.set()

        action = "accepted" if accept else "dismissed"
        self._pending.popleft()
        return f"Dialog {action}: '{pending.message[:80]}'"

    async def _handle_dialog(self, dialog: Dialog) -> None:
        """Core handler invoked by Playwright on dialog event."""
        dialog_type = dialog.type
        message = dialog.message
        default_value = dialog.default_value

        logger.info(
            "DialogManager: intercepted %s dialog: '%s'",
            dialog_type,
            message[:100],
        )

        if self._policy == DialogPolicy.WAIT_FOR_AGENT:
            await self._handle_wait_for_agent(dialog, dialog_type, message, default_value)
        elif self._policy == DialogPolicy.AUTO_ACCEPT:
            await dialog.accept(default_value)
            self._record(dialog_type, message, default_value, "accepted", "auto_accept")
        elif self._policy == DialogPolicy.AUTO_DISMISS:
            await dialog.dismiss()
            self._record(dialog_type, message, default_value, "dismissed", "auto_dismiss")
        else:
            await self._handle_smart(dialog, dialog_type, message, default_value)

    async def _handle_smart(
        self, dialog: Dialog, dialog_type: str, message: str, default_value: str
    ) -> None:
        """SMART policy: alert/confirm/beforeunload→accept, prompt→dismiss."""
        if dialog_type in ("alert", "confirm", "beforeunload"):
            await dialog.accept(default_value)
            self._record(dialog_type, message, default_value, "accepted", "smart")
        else:
            await dialog.dismiss()
            self._record(dialog_type, message, default_value, "dismissed", "smart")

    async def _handle_wait_for_agent(
        self, dialog: Dialog, dialog_type: str, message: str, default_value: str
    ) -> None:
        """WAIT_FOR_AGENT: hold dialog open until Agent responds or timeout."""
        pending = _PendingDialog(
            dialog_type=dialog_type,
            message=message,
            default_value=default_value,
            timestamp=time.time(),
        )
        self._pending.append(pending)

        try:
            await asyncio.wait_for(pending.resolved.wait(), timeout=self._timeout_s)
        except asyncio.TimeoutError:
            logger.warning(
                "DialogManager: WAIT_FOR_AGENT timeout (%.0fs) for %s '%s'. Falling back to SMART.",
                self._timeout_s,
                dialog_type,
                message[:80],
            )
            if dialog_type in ("alert", "confirm", "beforeunload"):
                await dialog.accept(default_value)
                self._record(dialog_type, message, default_value, "accepted", "timeout")
            else:
                await dialog.dismiss()
                self._record(dialog_type, message, default_value, "dismissed", "timeout")
            return

        if pending.accept:
            await dialog.accept(pending.prompt_text or default_value)
            self._record(dialog_type, message, default_value, "accepted", "agent")
        else:
            await dialog.dismiss()
            self._record(dialog_type, message, default_value, "dismissed", "agent")

    def _record(
        self,
        dialog_type: str,
        message: str,
        default_value: str,
        action_taken: str,
        handled_by: str,
    ) -> None:
        """Record a handled dialog to recent history."""
        record = DialogRecord(
            dialog_type=dialog_type,
            message=message,
            default_value=default_value,
            timestamp=time.time(),
            action_taken=action_taken,
            handled_by=handled_by,
        )
        self._recent.append(record)
        logger.info(
            "DialogManager: %s %s dialog '%s' (by %s)",
            action_taken,
            dialog_type,
            message[:60],
            handled_by,
        )

    def format_for_snapshot(self) -> str | None:
        """Format dialog info for inclusion in snapshot output.

        Returns None if no relevant dialog info to report.
        """
        parts: list[str] = []

        pending = self.get_pending()
        if pending:
            parts.append("[PENDING DIALOG - Action Required]")
            for p in pending:
                parts.append(f"  {p.dialog_type}: '{p.message}'")
            parts.append("  → Use browser_manage_tool action='dialog_response' value='accept' or 'dismiss' to respond.")

        recent = self.get_recent()
        if recent:
            for r in recent:
                parts.append(f"[Dialog auto-{r.action_taken}] {r.dialog_type}: '{r.message}'")

        if not parts:
            return None

        self.clear_recent()
        return "\n".join(parts)


@dataclass
class _PendingDialog:
    """Internal state for a dialog awaiting Agent response."""

    dialog_type: str
    message: str
    default_value: str
    timestamp: float
    resolved: asyncio.Event = field(default_factory=asyncio.Event)
    accept: bool = True
    prompt_text: str = ""
