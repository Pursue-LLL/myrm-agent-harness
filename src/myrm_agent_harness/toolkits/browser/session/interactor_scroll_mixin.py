"""Humanized wheel-burst scrolling behaviors for the Interactor.

[INPUT]
- pool.config::HumanizeConfig, HumanizeMode (POS: interaction humanization config)
- session.humanize::bezier_move, wheel_burst, scroll_notch_delta, scroll_burst_break_ms, scroll_phase_steps (POS: humanized delay, Bézier mouse, and wheel-burst scroll helpers)

[OUTPUT]
- ScrollHumanizeMixin: scroll-target cursor placement, wheel-burst inertial delivery,
  honest no-op reporting, and scroll_to_bottom progress loop
  (replaces Playwright's implicit scrollIntoViewIfNeeded)
- _parse_scroll_params: parse key=value tuning knobs for scroll_to_bottom

[POS]
Scroll humanization behaviors mixed into Interactor. Owns wheel-input scroll
delivery: cursor placement on the target scroll container, mode-specific inertial
delivery (FAST single wheel / DEFAULT burst / CAREFUL accel-cruise-decel rhythm),
honest outcome reporting, and the bottom-detection progress loop. CAREFUL
pre-interaction target centering lives in the sibling
interactor_scroll_targeting_mixin module; coordinate interaction and ref-action
dispatch live in sibling mixin/aggregate files.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.browser.pool.config import HumanizeMode
from myrm_agent_harness.toolkits.browser.session.humanize import (
    bezier_move,
    scroll_burst_break_ms,
    scroll_notch_delta,
    scroll_phase_steps,
    wheel_burst,
)

if TYPE_CHECKING:
    from patchright.async_api import Locator

logger = logging.getLogger(__name__)


# Post-scroll settle wait before re-measuring, so smooth-scroll animations that
# started on the wheel events have time to move before a no-op is reported.
_SCROLL_VERIFY_SETTLE_MS = 120
# Walks from elementFromPoint(x, y) up to the document and returns the metrics of
# the container a wheel event would actually scroll. Only real wheel-scrollable
# boxes count (overflow auto/scroll, or the document itself), so overflow:visible
# boxes that merely overflow are skipped — measuring them would always report
# scrollTop == 0 and falsely mark every scroll as stuck/no-op.
_SCROLL_MEASURE_JS = (
    "(({ x, y }) => {"
    "  const doc = document.scrollingElement || document.documentElement;"
    "  const isScrollable = (el) => {"
    "    if (!(el instanceof Element) || el.scrollHeight <= el.clientHeight + 1) return false;"
    "    if (el === doc) return true;"
    "    const s = getComputedStyle(el);"
    "    return s.overflowY === 'auto' || s.overflowY === 'scroll' || s.overflowY === 'overlay';"
    "  };"
    "  let node = document.elementFromPoint(x, y);"
    "  while (node && node !== doc) {"
    "    if (node instanceof HTMLIFrameElement) {"
    "      try {"
    "        const innerDoc = node.contentDocument;"
    "        const inner = innerDoc && (innerDoc.scrollingElement || innerDoc.documentElement);"
    "        if (inner && inner.scrollHeight > inner.clientHeight + 1) {"
    "          return { top: inner.scrollTop, height: inner.scrollHeight, client: inner.clientHeight };"
    "        }"
    "      } catch (_err) {"
    "        /* Cross-origin iframe: cannot introspect; fall through to ancestors. */"
    "      }"
    "    }"
    "    if (isScrollable(node)) {"
    "      return { top: node.scrollTop, height: node.scrollHeight, client: node.clientHeight };"
    "    }"
    "    node = node.parentElement;"
    "  }"
    "  return { top: doc.scrollTop, height: doc.scrollHeight, client: doc.clientHeight };"
    "})"
)

_SCROLL_TO_BOTTOM_MAX_STEPS_CAP = 1000
_SCROLL_TO_BOTTOM_DEFAULT_MAX_STEPS = 15
_SCROLL_TO_BOTTOM_DEFAULT_DELAY_MS = 500
_SCROLL_TO_BOTTOM_DEFAULT_STABLE_COUNT = 3


def _parse_scroll_params(text: str) -> dict[str, int]:
    """Parse key=value parameters from scroll_to_bottom text field.

    Accepts format: "max_steps=20,delay_ms=300,stable_count=3" (all optional).
    Returns dict with guaranteed keys: max_steps, delay_ms, stable_count.
    """
    params: dict[str, int] = {
        "max_steps": _SCROLL_TO_BOTTOM_DEFAULT_MAX_STEPS,
        "delay_ms": _SCROLL_TO_BOTTOM_DEFAULT_DELAY_MS,
        "stable_count": _SCROLL_TO_BOTTOM_DEFAULT_STABLE_COUNT,
    }
    if not text or not text.strip():
        return params

    for part in text.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        key = key.strip()
        val = val.strip()
        if key in params:
            with contextlib.suppress(ValueError):
                params[key] = int(val)

    params["max_steps"] = max(1, min(params["max_steps"], _SCROLL_TO_BOTTOM_MAX_STEPS_CAP))
    params["delay_ms"] = max(100, params["delay_ms"])
    params["stable_count"] = max(2, params["stable_count"])
    return params


class ScrollHumanizeMixin:
    """Humanized wheel-input scrolling, shared by ref and coordinate interaction paths."""

    async def _scroll_cursor_target(self, locator: Locator) -> tuple[float, float]:
        """Pick the best cursor point to dispatch wheel events from.

        Prefers the center of the target element (the scroll container) clamped into
        the viewport; falls back to the viewport center when the element is hidden.
        """
        viewport = self._page.viewport_size or {"width": 1280, "height": 720}
        vw, vh = viewport["width"], viewport["height"]
        try:
            await locator.wait_for(state="visible", timeout=2000)
            box = await locator.bounding_box(timeout=1000)
        except Exception:
            box = None
        if box:
            x = min(max(box["x"] + box["width"] / 2, 1.0), vw - 1.0)
            y = min(max(box["y"] + box["height"] / 2, 1.0), vh - 1.0)
            return x, y
        return vw / 2, vh / 2

    async def _scroll_move_cursor(self, x: float, y: float) -> None:
        """Move the mouse to a scroll target (Bézier trajectory in CAREFUL mode)."""
        if self._humanize.enable_bezier_mouse:
            await bezier_move(self._page, self._mouse_x, self._mouse_y, x, y, self._humanize)
        else:
            await self._page.mouse.move(x, y)
        self._mouse_x, self._mouse_y = x, y

    async def _scroll_measure(self, x: float, y: float) -> dict[str, float]:
        """Measure {top, height, client} of the scroll container under a point.

        Walks from elementFromPoint(x, y) up to the document so the measured
        container always matches the one a wheel event would scroll; only real
        wheel-scrollable containers count (overflow auto/scroll, or the document),
        so overflow:visible boxes that merely overflow are skipped. Same-origin
        iframes are introspected directly; cross-origin iframes fall through to
        their ancestors (progress detection degrades to the retarget-on-stuck path).
        """
        result = await self._page.evaluate(_SCROLL_MEASURE_JS, {"x": round(x), "y": round(y)})
        return {
            "top": float(result["top"]),
            "height": float(result["height"]),
            "client": float(result["client"]),
        }

    async def _scroll_with_report(self, x: float, y: float, delta: int, suffix: str) -> str:
        """Deliver a wheel scroll and report the honest outcome.

        Measures the target container before delivery, then verifies movement
        afterwards (one immediate check plus one after a short settle, covering
        smooth-scroll animations). When nothing moved, the no-op is classified
        so the agent is never told a success that did not happen.
        """
        before = await self._scroll_measure(x, y)
        await self._scroll_deliver(delta)
        reason = await self._scroll_noop_reason(x, y, before, delta)
        return f"Scrolled {delta}px{suffix}{reason}"

    async def _scroll_noop_reason(self, x: float, y: float, before: dict[str, float], delta: int) -> str:
        """Empty when the container moved, else an honest parenthetical reason."""
        if (await self._scroll_measure(x, y))["top"] != before["top"]:
            return ""
        await asyncio.sleep(_SCROLL_VERIFY_SETTLE_MS / 1000.0)
        after = await self._scroll_measure(x, y)
        if after["top"] != before["top"]:
            return ""
        if after["height"] <= after["client"] + 1:
            return " (no scrollable overflow)"
        if delta > 0 and after["top"] >= after["height"] - after["client"] - 1:
            return " (already at the bottom)"
        if delta < 0 and after["top"] <= 0:
            return " (already at the top)"
        return " (no visible movement; smooth-scroll or blocked wheel)"

    async def _scroll_to_bottom_loop(
        self,
        locator: Locator,
        params: dict[str, int],
        healed_msg: str,
    ) -> str:
        """Scroll a target container to its bottom with humanized wheel bursts.

        Progress is measured on the real wheel-scrollable container under the
        cursor: each iteration wheels one viewport height, then re-measures.
        Stalls are handled honestly — the container is retargeted once when a
        wheel lands on a no-longer-responsive box, and reported as ``stuck``
        rather than a false success. Returns a humanized status summary.
        """
        max_steps = params["max_steps"]
        delay_ms = params["delay_ms"]
        stable_count = params["stable_count"]

        start_time = time.monotonic()
        target_x, target_y = await self._scroll_cursor_target(locator)
        await self._scroll_move_cursor(target_x, target_y)
        viewport_h = await self._page.evaluate("window.innerHeight")
        if viewport_h <= 0:
            viewport_h = 800

        state = await self._scroll_measure(target_x, target_y)
        if state["height"] <= state["client"] + 1:
            elapsed = round(time.monotonic() - start_time, 1)
            return (
                f"Scrolled 0 steps ({elapsed}s). "
                f"Height: {state['height']}\u2192{state['height']}px. "
                f"Status: completed (no scrollable overflow){healed_msg}"
            )
        prev_top = state["top"]
        prev_height = state["height"]
        start_height = prev_height
        stable = 0
        steps = 0
        repositioned = False
        stuck = False

        while steps < max_steps:
            await self._scroll_deliver(viewport_h)
            await asyncio.sleep(delay_ms / 1000.0)
            state = await self._scroll_measure(target_x, target_y)
            steps += 1

            moved = state["top"] != prev_top
            grew = state["height"] > prev_height
            if moved or grew:
                stable = 0
                prev_top = state["top"]
                prev_height = state["height"]
                continue

            can_scroll = state["height"] > state["client"] + state["top"] + 1
            if can_scroll and not repositioned:
                # Wheel hit a container that no longer responds — retarget once.
                target_x, target_y = await self._scroll_cursor_target(locator)
                await self._scroll_move_cursor(target_x, target_y)
                prev_top = state["top"]
                prev_height = state["height"]
                repositioned = True
                continue

            if can_scroll:
                stuck = True
                break

            stable += 1
            if stable >= stable_count:
                break

        elapsed = round(time.monotonic() - start_time, 1)
        if stuck:
            status = "stuck"
        elif stable >= stable_count:
            status = "completed"
        else:
            status = "max_reached"
        return (
            f"Scrolled {steps} steps ({elapsed}s). "
            f"Height: {start_height}\u2192{state['height']}px. "
            f"Status: {status}{healed_msg}"
        )

    async def _scroll_deliver(self, delta: int) -> None:
        """Deliver a relative scroll with mode-appropriate humanization.

        FAST sends a single wheel event (fastest, no humanization cost).
        DEFAULT delivers the delta as a burst of small wheel notches (trackpad-like).
        CAREFUL adds a burst-group rhythm (accel/cruise/decel notch sizes, pauses on
        group boundaries and phase transitions, occasional reading pause), a pre-move
        delay, and an occasional overshoot + correction before settling.
        """
        if delta == 0:
            return
        if self._humanize.mode == HumanizeMode.FAST:
            await self._page.mouse.wheel(0, delta)
            return
        if self._humanize.mode == HumanizeMode.CAREFUL:
            await asyncio.sleep(random.randint(*self._humanize.scroll_pre_move_delay) / 1000.0)
            direction = 1 if delta > 0 else -1
            accel, decel = scroll_phase_steps(self._humanize)
            avg_delta = (self._humanize.scroll_delta_base[0] + self._humanize.scroll_delta_base[1]) / 2
            total_notches = max(accel + decel + 1, round(abs(delta) / avg_delta))
            phases = ["accel"] * accel + ["cruise"] * max(0, total_notches - accel - decel) + ["decel"] * decel
            remaining = abs(delta)
            group_left = random.randint(2, 4)
            index = 0
            while remaining > 0:
                if index >= len(phases):
                    phases.append("cruise")  # delta exceeds the planned notch sum
                phase = phases[index]
                notch = scroll_notch_delta(self._humanize, phase, direction)
                if direction > 0:
                    notch = min(notch, remaining)
                else:
                    notch = max(notch, -remaining)
                await wheel_burst(self._page, notch, self._humanize)
                remaining -= abs(notch)
                index += 1
                if remaining <= 0:
                    break
                next_phase = phases[index] if index < len(phases) else "cruise"
                pause = scroll_burst_break_ms(
                    self._humanize,
                    in_burst=group_left > 0,
                    phase_changed=next_phase != phase,
                )
                if pause:
                    await asyncio.sleep(pause / 1000.0)
                    group_left = random.randint(2, 4)
                else:
                    group_left -= 1
            await self._scroll_overshoot_correct(direction)
        else:
            await wheel_burst(self._page, delta, self._humanize)

    async def _scroll_overshoot_correct(self, direction: int) -> None:
        """CAREFUL-only: optional overshoot past the target, then correct back."""
        if random.random() < self._humanize.scroll_overshoot_chance:
            overshoot = random.randint(*self._humanize.scroll_overshoot_px) * direction
            await wheel_burst(self._page, overshoot, self._humanize)
            await asyncio.sleep(random.randint(*self._humanize.scroll_settle_delay) / 1000.0)
            for _ in range(random.randint(1, 2)):
                correction = random.randint(40, 80) * -direction
                await wheel_burst(self._page, correction, self._humanize)
                await asyncio.sleep(random.randint(100, 250) / 1000.0)
        else:
            await asyncio.sleep(random.randint(*self._humanize.scroll_settle_delay) / 1000.0)
