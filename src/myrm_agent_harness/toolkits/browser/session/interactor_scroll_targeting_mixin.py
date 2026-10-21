"""CAREFUL pre-interaction target centering for the Interactor.

[INPUT]
- pool.config::HumanizeConfig (POS: interaction humanization config)
- patchright.async_api::Locator (POS: element locator)
- session.interactor_scroll_mixin::ScrollHumanizeMixin (POS: wheel-burst delivery, cursor placement, progress loop)

[OUTPUT]
- ScrollTargetingMixin: bring an interaction target into view with humanized
  wheel scrolls (replaces Playwright's implicit scrollIntoViewIfNeeded)

[POS]
CAREFUL-mode pre-interaction target centering. Probes a target's real rendered
state (elementFromPoint hit-test, nearest wheel-scrollable ancestor, exact wheel
delta), then wheels it into the viewport center band using the same humanized
delivery as explicit scrolls. Depends on the delivery primitives of
ScrollHumanizeMixin; mixed into Interactor before it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Locator

logger = logging.getLogger(__name__)


# Max humanized wheel steps used to bring an interaction target into the
# viewport center band before a CAREFUL interaction proceeds. Each step settles,
# so the bound keeps worst-case latency sane on nested/cross-origin containers.
_TARGET_SCROLL_MAX_STEPS = 6

# Runs inside the target's own frame (main page or same-origin iframe) and reads
# its *rendered* state: bounding box in frame-local coords, whether the target is
# actually visible to the user (elementFromPoint hit-test — a target clipped by a
# nested scroll container or an iframe viewport reads as invisible even though its
# geometry lies inside the page viewport), whether the probe ran in the top frame,
# and — when invisible — the nearest wheel-scrollable ancestor plus the exact wheel
# delta that centers the target in it. The delta is computed from frame-local
# relative positions, so it is origin-independent and works across iframes.
_TARGET_PROBE_JS = (
    "((el) => {"
    "  const r = el.getBoundingClientRect();"
    "  const cx = r.x + r.width / 2;"
    "  const cy = r.y + r.height / 2;"
    "  const hit = document.elementFromPoint(cx, cy);"
    "  const visible = !!hit && (hit === el || el.contains(hit));"
    "  const out = {"
    "    x: r.x, y: r.y, width: r.width, height: r.height,"
    "    visible,"
    "    is_top: window === window.top,"
    "    container: null,"
    "  };"
    "  const doc = document.scrollingElement || document.documentElement;"
    "  const isScrollable = (n) => {"
    "    if (n === doc) return n.scrollHeight > n.clientHeight + 1;"
    "    if (!(n instanceof Element) || n.scrollHeight <= n.clientHeight + 1) return false;"
    "    const s = getComputedStyle(n);"
    "    return s.overflowY === 'auto' || s.overflowY === 'scroll' || s.overflowY === 'overlay';"
    "  };"
    "  let node = el.parentElement;"
    "  while (node) {"
    "    if (isScrollable(node)) {"
    "      const cb = node.getBoundingClientRect();"
    "      /* Document-relative top of the target inside the container's content:"
    "         for a scroller div, r.top - cb.top is the on-screen offset and needs"
    "         scrollTop added; for the document element the layout rect itself"
    "         shifts with the scroll (cb.top === -scrollTop), so it already yields"
    "         the document-relative position and must NOT be added again. */"
    "      const targetTop = r.top - cb.top + (node === doc ? 0 : node.scrollTop);"
    "      const desiredScroll = targetTop + r.height / 2 - node.clientHeight / 2;"
    "      out.container = {"
    "        left: cb.left, top: cb.top,"
    "        /* client* is the *visible* box: for the document element the"
    "           layout rect grows with the content, which would place the wheel"
    "           dispatch point outside the frame's visible area. */"
    "        width: node.clientWidth, height: node.clientHeight,"
    "        is_doc: node === doc,"
    "        delta: Math.round(desiredScroll - node.scrollTop),"
    "      };"
    "      break;"
    "    }"
    "    node = node.parentElement;"
    "  }"
    "  return out;"
    "})"
)


class ScrollTargetingMixin:
    """CAREFUL pre-interaction target centering with humanized wheel scrolls."""

    async def _target_box(self, locator: Locator) -> dict[str, float] | None:
        """Viewport box of a ref target, or None when it cannot be measured.

        ``bounding_box`` is a pure geometry read — unlike locator actions it never
        triggers Playwright's implicit scrollIntoViewIfNeeded — so it is safe to
        call before deciding whether a humanized scroll is needed. The wait uses
        ``attached`` rather than ``visible`` because visibility semantics vary by
        context (an iframe-clipped element reads invisible even when it is laid
        out); real visibility is decided by the rendered-state probe instead.
        """
        try:
            await locator.wait_for(state="attached", timeout=5000)
            box = await locator.bounding_box(timeout=1000)
        except Exception:
            return None
        if box is None or "y" not in box or "height" not in box:
            return None
        return box

    async def _target_probe(self, locator: Locator) -> dict | None:
        """Probe a target's real rendered state via JS.

        Returns the target's frame-local box, whether it is actually visible
        (elementFromPoint hit-test, so elements clipped by nested scroll
        containers or iframe viewports read as invisible), whether the probe ran
        in the top frame, and — when invisible — the nearest wheel-scrollable
        ancestor with the exact wheel delta that centers the target in it.
        Returns None on any measure error so callers degrade silently. The wait
        is on ``attached`` only: visibility is decided by the probe itself, since
        patchright's ``visible`` semantics reject iframe-clipped targets.
        """
        try:
            await locator.wait_for(state="attached", timeout=5000)
            return await locator.evaluate(_TARGET_PROBE_JS)
        except Exception:
            return None

    async def _ensure_target_in_view(self, locator: Locator) -> bool:
        """Bring a CAREFUL interaction target into view with humanized wheel scrolls.

        Replaces Playwright's implicit one-shot ``scrollIntoViewIfNeeded`` (instant
        JS jump, no wheel events) with the same humanized wheel stack used by
        explicit scrolls. Three cases are distinguished from the target's rendered
        state rather than from geometry alone:

        - Target clipped by an ancestor scroll container (nested scrollers,
          iframes): the nearest wheel-scrollable ancestor is wheeled until the
          target is actually visible, so the following click lands on the target.
        - Target visible inside the top frame but outside the center band: wheeled
          toward the band on the main document.
        - Target visible in a nested/iframe container: no further scrolling — the
          main-viewport center band is meaningless for clipped containers.

        Returns True when a wheel scroll happened. Best-effort by contract: any
        failure (page navigating/closed mid-wheel, measure errors, ...) degrades
        silently to False, because the action itself still runs through its normal
        path afterwards.
        """
        if not self._humanize.enable_bezier_mouse:
            return False
        try:
            zone = self._humanize.scroll_target_zone
            viewport = self._page.viewport_size or {"width": 1280, "height": 720}
            vw, vh = float(viewport["width"]), float(viewport["height"])
            zone_lo, zone_hi = vh * zone[0], vh * zone[1]

            moved = False
            for _ in range(_TARGET_SCROLL_MAX_STEPS):
                box = await self._target_box(locator)
                if box is None:
                    break
                probe = await self._target_probe(locator)
                if probe is None:
                    break
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                container = probe.get("container")

                if probe["visible"]:
                    if not probe["is_top"] or (container and not container["is_doc"]):
                        break  # nested/iframe target already visible — interaction can proceed
                    if zone_lo <= cy <= zone_hi:
                        break
                    delta = round(cy - (zone_hi if cy > zone_hi else zone_lo))
                    if delta == 0:
                        break
                    await self._scroll_move_cursor(min(max(cx, 1.0), vw - 1.0), min(max(cy, 1.0), vh - 1.0))
                    await self._scroll_deliver(delta)
                    moved = True
                    continue

                if not container or container["delta"] == 0:
                    break
                # Wheel dispatch must land inside the target's scroll container.
                # Its center in frame-local coords, translated to main-page coords
                # via the delta between the target's Playwright box (main-page)
                # and its frame-local box returned by the probe.
                c_cx = cx + (container["left"] + container["width"] / 2 - probe["x"] - probe["width"] / 2)
                c_cy = cy + (container["top"] + container["height"] / 2 - probe["y"] - probe["height"] / 2)
                await self._scroll_move_cursor(min(max(c_cx, 1.0), vw - 1.0), min(max(c_cy, 1.0), vh - 1.0))
                await self._scroll_deliver(container["delta"])
                moved = True
            return moved
        except Exception as e:
            logger.debug(f"Interactor: pre-interaction scroll skipped: {e}")
            return False
