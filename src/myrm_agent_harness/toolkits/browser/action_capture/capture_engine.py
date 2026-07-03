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

This module is agent-agnostic — it operates on a raw Playwright Page and has
zero imports from `agent/`, `runtime/`, or `backends/`.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .types import ActionStep, ActionType, CaptureSession

if TYPE_CHECKING:
    from patchright.async_api import Page

logger = logging.getLogger(__name__)

_CAPTURE_JS = """
(function() {
  if (window.__myrmActionCapture) return;

  const SENSITIVE_TYPES = new Set(['password', 'credit-card-number', 'cc-csc']);

  function getSelector(el) {
    if (el.id) return '#' + CSS.escape(el.id);
    if (el.getAttribute('data-testid')) return '[data-testid="' + el.getAttribute('data-testid') + '"]';
    if (el.getAttribute('aria-label')) return '[aria-label="' + el.getAttribute('aria-label') + '"]';
    if (el.getAttribute('name')) return el.tagName.toLowerCase() + '[name="' + el.getAttribute('name') + '"]';

    const tag = el.tagName.toLowerCase();
    const parent = el.parentElement;
    if (!parent) return tag;
    const siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
    if (siblings.length === 1) return getSelector(parent) + ' > ' + tag;
    const idx = siblings.indexOf(el) + 1;
    return getSelector(parent) + ' > ' + tag + ':nth-child(' + idx + ')';
  }

  function getRole(el) {
    return el.getAttribute('role') || el.tagName.toLowerCase();
  }

  function isSensitive(el) {
    const type = (el.getAttribute('type') || '').toLowerCase();
    const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
    return type === 'password' || SENSITIVE_TYPES.has(ac);
  }

  function getText(el) {
    const label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
    if (label) return label;
    const text = (el.textContent || '').trim();
    return text.length > 80 ? text.slice(0, 80) + '...' : text;
  }

  function emit(action, el, value) {
    if (!window.__myrmCaptureActive) return;
    window.__myrmCaptureCallback(JSON.stringify({
      action: action,
      selector: getSelector(el),
      value: value || '',
      url: location.href,
      title: document.title,
      elementText: getText(el),
      elementRole: getRole(el),
      isPassword: isSensitive(el),
      ts: Date.now() / 1000
    }));
  }

  document.addEventListener('click', function(e) {
    const el = e.target.closest('a, button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="menuitem"], label');
    if (el) emit('click', el);
  }, true);

  document.addEventListener('dblclick', function(e) {
    const el = e.target.closest('a, button, input, select, textarea, [role="button"]');
    if (el) emit('dblclick', el);
  }, true);

  document.addEventListener('change', function(e) {
    const el = e.target;
    if (!el || !el.tagName) return;
    const tag = el.tagName.toLowerCase();
    if (tag === 'select') {
      emit('select', el, el.value);
    } else if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) {
      emit(el.checked ? 'check' : 'uncheck', el, String(el.checked));
    } else if (tag === 'input' && el.type === 'file') {
      const names = Array.from(el.files || []).map(f => f.name).join(', ');
      emit('upload', el, names);
    }
  }, true);

  let inputTimer = null;
  let lastInputEl = null;
  document.addEventListener('input', function(e) {
    const el = e.target;
    if (!el || !el.tagName) return;
    const tag = el.tagName.toLowerCase();
    if (tag !== 'input' && tag !== 'textarea') return;
    if (el.type === 'checkbox' || el.type === 'radio' || el.type === 'file') return;

    lastInputEl = el;
    clearTimeout(inputTimer);
    inputTimer = setTimeout(function() {
      if (lastInputEl) {
        const val = isSensitive(lastInputEl) ? '***' : lastInputEl.value;
        emit('type', lastInputEl, val);
        lastInputEl = null;
      }
    }, 600);
  }, true);

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === 'Escape' || e.key === 'Tab') {
      const el = e.target;
      if (el && el.tagName) emit('press', el, e.key);
    }
  }, true);

  window.__myrmActionCapture = true;
  window.__myrmCaptureActive = true;
})();
"""


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
                self._attached = True

            await self._page.add_init_script(_CAPTURE_JS)
            await self._page.evaluate(_CAPTURE_JS)

            self._page.on("framenavigated", self._on_navigation)

            logger.info(f"Action capture started: session={session_id}")
            return self._session

    async def stop(self) -> CaptureSession | None:
        """Stop capture and return the completed session."""
        async with self._lock:
            if not self._session:
                return None
            self._session.status = "stopped"
            try:
                await self._page.evaluate("window.__myrmCaptureActive = false")
            except Exception:
                pass
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
            try:
                await self._page.evaluate("window.__myrmCaptureActive = false")
            except Exception:
                pass

    async def resume(self) -> None:
        """Resume paused capture."""
        if self._session and self._session.status == "paused":
            self._session.status = "recording"
            try:
                await self._page.evaluate("window.__myrmCaptureActive = true")
            except Exception:
                pass

    async def _on_action_event(self, raw_json: str) -> None:
        """Bridge callback invoked from JS — parse and dispatch."""
        import json

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

        screenshot_b64: str | None = None
        if self._capture_screenshots:
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
        )

        self._session.add_step(step)

        for cb in self._callbacks:
            try:
                await cb.on_step(step)
            except Exception:
                logger.exception("Capture callback error")

    async def _on_navigation(self, frame: object) -> None:
        """Re-inject capture script after same-page navigations."""
        if not self._session or self._session.status != "recording":
            return
        try:
            page_frame = self._page.main_frame
            if hasattr(frame, "url") and frame == page_frame:
                url = getattr(frame, "url", "")
                step = ActionStep(
                    seq=self._session.next_seq,
                    action=ActionType.NAVIGATE,
                    selector="",
                    value=url,
                    url=url,
                    title="",
                )
                self._session.add_step(step)

                for cb in self._callbacks:
                    try:
                        await cb.on_step(step)
                    except Exception:
                        logger.exception("Capture callback error on navigation")
        except Exception:
            logger.debug("Navigation capture failed (page may have closed)")
