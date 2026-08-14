"""Browser action capture engine — Playwright CDP event listener.


[INPUT]
- patchright.async_api::Page (POS: Playwright page instance for event attachment)
- types::ActionStep, ActionType, CaptureSession (POS: structured action models)

[OUTPUT]
- ActionCaptureEngine: start/stop/pause/resume capture on a Playwright Page
- CaptureCallback: Protocol for real-time step notification

[POS]
Core engine that attaches JavaScript event listeners to a Playwright Page via
`page.expose_function` + `page.add_init_script`. Captured DOM events are
forwarded to Python via a bridge function, structured into ActionStep objects,
and dispatched to registered callbacks (e.g. SSE, WebSocket).

Recording quality notes:
- Text input uses a session-based fill model: focus starts a session, each
  keystroke only syncs the value, and the final value is emitted once on
  commit (blur / click-away / change / navigation / pagehide). This avoids
  fragmented `type` steps produced by debounce-based capture, which would be
  re-typed append-style on replay.
- IME composition (Chinese input) is protected: in-progress pinyin is never
  emitted as fragments, and Enter/Escape presses during composition (candidate
  selection/cancellation) are not recorded as page-level actions.
- Unchanged or empty values are dropped (no-op focus, clear-without-commit).
- Enter-press clicks are deduplicated via a keyboard-activation window.
- Multi-select records every selected option value plus its readable label
  (option label, falling back to text/value) so generated skills are both
  lossless and self-describing; single-value selects stay minimal.
- Autocomplete/typeahead option clicks fold into the active fill session.
- Clicks on search/chat chrome that only focus the nearby input fold into the
  fill session (search-style selectors only; form submit buttons unaffected).
- Event targets resolve through open shadow DOM boundaries via `composedPath`
  so selectors point at the real element rather than the shadow host.
- SPA navigations (history.pushState/replaceState, hash changes) are reported
  through the bridge and folded together with real browser navigations.
- Navigation folding lives on the Python side (`_record_navigation`):
  consecutive navigations collapse to the final hop, and a navigation that
  immediately follows an action step is merged into that step's URL instead of
  emitting a redundant NAVIGATE step.

This module is agent-agnostic — it operates on a raw Playwright Page and has
zero imports from `agent/`, `runtime/`, or `backends/`.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
import uuid
from dataclasses import replace
from importlib.resources import files
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .types import ActionStep, ActionType, CaptureSession

if TYPE_CHECKING:
    from patchright.async_api import Page

logger = logging.getLogger(__name__)

# A navigation arriving within this window after an action step (click/dblclick/press)
# is considered caused by that action and folded into its URL instead of producing
# a standalone NAVIGATE step. Mirrors BrowserSkill's `expects_navigation` semantics.
_NAV_ACTION_WINDOW_S = 1.5

_CAPTURE_JS = (
    files(__package__).joinpath("capture_script.js").read_text(encoding="utf-8")
)


@runtime_checkable
class CaptureCallback(Protocol):
    """Protocol for receiving captured action steps in real-time."""

    async def on_step(self, step: ActionStep) -> None: ...


class ActionCaptureEngine:
    """Playwright-based browser action capture engine.

    Attaches JS event listeners to a Page and bridges DOM events back to Python
    via `page.expose_function`. Thread-safe for concurrent SSE consumers.
    """

    def __init__(self, page: Page, *, capture_screenshots: bool = True) -> None:
        self._page = page
        self._capture_screenshots = capture_screenshots
        self._session: CaptureSession | None = None
        self._callbacks: list[CaptureCallback] = []
        self._attached = False
        self._lock = asyncio.Lock()

    @property
    def session(self) -> CaptureSession | None:
        return self._session

    def add_callback(self, cb: CaptureCallback) -> None:
        self._callbacks.append(cb)

    def remove_callback(self, cb: CaptureCallback) -> None:
        with contextlib.suppress(ValueError):
            self._callbacks.remove(cb)

    async def start(self, start_url: str = "") -> CaptureSession:
        """Start a new capture session on the attached page."""
        async with self._lock:
            session_id = uuid.uuid4().hex[:12]
            self._session = CaptureSession(
                session_id=session_id,
                start_url=start_url or self._page.url,
            )

            if not self._attached:
                await self._page.expose_function(
                    "__myrmCaptureCallback",
                    self._on_action_event,
                )
                self._page.on("framenavigated", self._on_navigation)
                self._attached = True

            await self._inject_capture(active=True)

            logger.info(f"Action capture started: session={session_id}")
            return self._session

    async def stop(self) -> CaptureSession | None:
        """Stop capture and return the completed session."""
        async with self._lock:
            if not self._session:
                return None
            self._session.status = "stopped"
            await self._inject_capture(active=False)
            session = self._session
            logger.info(
                f"Action capture stopped: session={session.session_id}, "
                f"steps={len(session.steps)}"
            )
            return session

    async def pause(self) -> None:
        """Pause capture (events are silently dropped on the JS side)."""
        if self._session and self._session.status == "recording":
            self._session.status = "paused"
            await self._inject_capture(active=False)

    async def resume(self) -> None:
        """Resume paused capture."""
        if self._session and self._session.status == "paused":
            self._session.status = "recording"
            await self._inject_capture(active=True)

    async def _inject_capture(self, *, active: bool) -> None:
        """(Re)inject capture listeners and sync the active gate in one world.

        `add_init_script` is deliberately not used: it targets the main world
        while `page.evaluate` defaults to the isolated world, and a main-world
        context is only materialized lazily after navigation — listeners would
        silently stop firing. Injecting via `evaluate` keeps every listener in
        the same world as the state gate, so stop/pause/resume always control
        exactly the listeners that produce steps. Re-injection is idempotent:
        `capture_script.js` guards on `window.__myrmActionCapture`.
        """
        try:
            await self._page.evaluate(_CAPTURE_JS)
            await self._page.evaluate(
                f"window.__myrmCaptureActive = {'true' if active else 'false'}"
            )
        except Exception:
            logger.debug("Capture injection failed (page may have closed)")

    async def _on_action_event(self, raw_json: str) -> None:
        """Bridge callback invoked from JS — parse and dispatch."""
        if not self._session or self._session.status != "recording":
            return

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from capture bridge")
            return

        action_str = data.get("action", "")
        try:
            action_type = ActionType(action_str)
        except ValueError:
            logger.debug(f"Unknown action type: {action_str}")
            return

        # SPA navigations reported from JS are folded here together with real
        # navigations (same collapsing rules, no screenshot, no step push).
        if action_type == ActionType.NAVIGATE:
            await self._record_navigation(data.get("url", ""))
            return

        screenshot_b64: str | None = None
        if self._capture_screenshots and action_type != ActionType.HOVER:
            try:
                raw = await self._page.screenshot(type="png", timeout=3000)
                screenshot_b64 = base64.b64encode(raw).decode("ascii")
            except Exception:
                pass

        step = ActionStep(
            seq=self._session.next_seq,
            action=action_type,
            selector=data.get("selector", ""),
            value=data.get("value", ""),
            url=data.get("url", ""),
            title=data.get("title", ""),
            timestamp=data.get("ts", 0.0),
            screenshot_b64=screenshot_b64,
            element_text=data.get("elementText", ""),
            element_role=data.get("elementRole", ""),
            is_password=data.get("isPassword", False),
            modifiers=data.get("modifiers", []),
            label=data.get("label", ""),
        )

        self._session.add_step(step)

        for cb in self._callbacks:
            try:
                await cb.on_step(step)
            except Exception:
                logger.exception("Capture callback error")

    async def _on_navigation(self, frame: object) -> None:
        """Handle frame navigation events during recording."""
        if not self._session or self._session.status != "recording":
            return
        try:
            page_frame = self._page.main_frame
            if hasattr(frame, "url") and frame == page_frame:
                # The previous document's JS context (and its listeners) was
                # destroyed by navigation, so listeners must be re-injected
                # before the next interaction can be recorded.
                await self._inject_capture(active=True)
                await self._record_navigation(getattr(frame, "url", ""))
        except Exception:
            logger.debug("Navigation capture failed (page may have closed)")

    async def _record_navigation(self, url: str) -> None:
        """Record a NAVIGATE step, folding redundant hops.

        Two folding rules:
        1. A navigation arriving within `_NAV_ACTION_WINDOW_S` after a click /
           dblclick / press step is caused by that action — the step's URL is
           updated to the destination and no standalone NAVIGATE is emitted.
        2. Consecutive NAVIGATE steps collapse to the last hop (redirect chains).
        """
        steps = self._session.steps

        def _updated(step: ActionStep, **overrides: object) -> ActionStep:
            return replace(step, **overrides)

        if steps:
            last = steps[-1]
            now = time.time()
            action_follow = last.action in {
                ActionType.CLICK,
                ActionType.DBLCLICK,
                ActionType.PRESS,
            }
            if action_follow and (now - last.timestamp) < _NAV_ACTION_WINDOW_S:
                steps[-1] = _updated(last, url=url)
                return

            if last.action == ActionType.NAVIGATE:
                steps[-1] = _updated(last, value=url, url=url)
                return

        self._session.add_step(
            ActionStep(
                seq=self._session.next_seq,
                action=ActionType.NAVIGATE,
                selector="",
                value=url,
                url=url,
                title="",
            )
        )
