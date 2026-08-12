"""Element interaction — single responsibility.


[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)
- snapshot::RefInfo (POS: element ref metadata)
- snapshot::resolve_locator (POS: rebuild Locator from RefInfo)
- exceptions::RefNotFoundError (POS: structured ref-not-found exception)
- pool.config::HumanizeConfig (POS: interaction humanization config)
- session.humanize::click_delay, type_delay, bezier_move, wheel_burst, scroll_notch_delta, scroll_burst_break_ms, scroll_phase_steps (POS: humanized delay, Bézier mouse, and wheel-burst scroll helpers)

[OUTPUT]
- Interactor: element interaction manager (supports humanized delays + Bézier mouse via HumanizeConfig)
- RefNotFoundMetrics: ref failure statistics (global + sliding window failure rate, top refs/actions with cache optimization)

[POS]
Element interaction manager. Responsibilities:
1. Ref-based operations (15 actions: click/dblclick/type/fill/fill_credential/press/hover/focus/select/scroll/scroll_to_bottom/upload_file/drag/check/uncheck)
2. Coordinate-based operations (7 actions via interact_at: click/dblclick/type/press/hover/scroll/drag — for canvas/rich-editor pages)
3. Ref resolution (from ref ID to Locator, supports iframe refs)
4. Viewport bounds validation (coordinate mode)
5. Interaction timeout control (10s)
6. Ref failure diagnosis (URL change detection + smart suggestion generation + context refs sampling)
7. Failure monitoring (failure rate, hot refs, hot actions statistics + periodic log output)

Single responsibility: only handles element interaction logic; does not handle navigation, snapshot, extraction, etc. Tab-level URL state is managed by TabController.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from myrm_agent_harness.core.security.redact import redact_sensitive_text
from myrm_agent_harness.toolkits.browser.exceptions import RefNotFoundError
from myrm_agent_harness.toolkits.browser.pool.config import HumanizeConfig, HumanizeMode
from myrm_agent_harness.toolkits.browser.session.humanize import (
    bezier_move,
    click_delay,
    scroll_burst_break_ms,
    scroll_notch_delta,
    scroll_phase_steps,
    type_delay,
    wheel_burst,
)
from myrm_agent_harness.toolkits.browser.snapshot import resolve_locator

if TYPE_CHECKING:
    from patchright.async_api import Frame, Locator, Page

    from myrm_agent_harness.toolkits.browser.snapshot import RefInfo

logger = logging.getLogger(__name__)


@dataclass
class RefNotFoundMetrics:
    """Ref-not-found statistics data.

    Provides both global and sliding-window (last 100) failure-rate views,
    with cached top refs/actions queries.

    Attributes:
        total_failures: Total failure count.
        total_interactions: Total interaction count.
        failure_refs: Failure count per ref (ref_id -> count).
        failure_by_action: Failure count per action type.
    """

    total_failures: int = 0
    total_interactions: int = 0
    failure_refs: dict[str, int] = field(default_factory=dict)
    failure_by_action: dict[str, int] = field(default_factory=dict)

    _recent_failures: deque[bool] = field(
        default_factory=lambda: deque(maxlen=100), init=False, repr=False
    )
    _cached_top_refs: list[tuple[str, int]] | None = field(
        default=None, init=False, repr=False
    )
    _cached_top_actions: list[tuple[str, int]] | None = field(
        default=None, init=False, repr=False
    )

    def record_interaction(
        self, failed: bool, ref: str | None = None, action: str | None = None
    ) -> None:
        """Record a single interaction result.

        Args:
            failed: Whether the ref lookup failed.
            ref: The failed ref ID (only required on failure).
            action: The failed action (only required on failure).
        """
        self.total_interactions += 1
        self._recent_failures.append(failed)

        if failed:
            self.total_failures += 1
            if ref:
                self.failure_refs[ref] = self.failure_refs.get(ref, 0) + 1
            if action:
                self.failure_by_action[action] = (
                    self.failure_by_action.get(action, 0) + 1
                )
            self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        """Invalidate the sorted-result cache."""
        self._cached_top_refs = None
        self._cached_top_actions = None

    @property
    def failure_rate(self) -> float:
        """Global failure rate (0.0-1.0)."""
        if self.total_interactions == 0:
            return 0.0
        return self.total_failures / self.total_interactions

    @property
    def recent_failure_rate(self) -> float:
        """Recent failure rate over the last 100 interactions (0.0-1.0)."""
        if not self._recent_failures:
            return 0.0
        return sum(self._recent_failures) / len(self._recent_failures)

    @property
    def top_failed_refs(self) -> list[tuple[str, int]]:
        """Top failed refs sorted by count descending (max 10, cached)."""
        if self._cached_top_refs is None:
            self._cached_top_refs = sorted(
                self.failure_refs.items(), key=lambda x: x[1], reverse=True
            )[:10]
        return self._cached_top_refs

    @property
    def top_failed_actions(self) -> list[tuple[str, int]]:
        """Top failed actions sorted by count descending (cached)."""
        if self._cached_top_actions is None:
            self._cached_top_actions = sorted(
                self.failure_by_action.items(), key=lambda x: x[1], reverse=True
            )
        return self._cached_top_actions

    def to_dict(self) -> dict[str, object]:
        """Export metrics as a dict for logging and monitoring.

        Returns:
            Dict containing all metrics and computed properties.
        """
        return {
            "total_failures": self.total_failures,
            "total_interactions": self.total_interactions,
            "failure_rate": self.failure_rate,
            "recent_failure_rate": self.recent_failure_rate,
            "top_failed_refs": self.top_failed_refs,
            "top_failed_actions": self.top_failed_actions,
        }


_INTERACTION_TIMEOUT_MS = 10_000
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
    "        // Cross-origin iframe: cannot introspect; fall through to ancestors."
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
_VALID_ACTIONS = frozenset(
    {
        "click",
        "dblclick",
        "type",
        "fill",
        "press",
        "hover",
        "focus",
        "select",
        "scroll",
        "scroll_to_bottom",
        "upload_file",
        "drag",
        "check",
        "uncheck",
        "fill_credential",
    }
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

    params["max_steps"] = max(
        1, min(params["max_steps"], _SCROLL_TO_BOTTOM_MAX_STEPS_CAP)
    )
    params["delay_ms"] = max(100, params["delay_ms"])
    params["stable_count"] = max(2, params["stable_count"])
    return params


class Interactor:
    """Element interaction manager — single responsibility.

    Responsibilities:
    1. Ref-based actions (15 types: click/dblclick/type/fill/fill_credential/press/hover/focus/select/scroll/scroll_to_bottom/upload_file/drag/check/uncheck)
    2. Coordinate-based actions (7 types via interact_at: click/dblclick/type/press/hover/scroll/drag)
    3. Ref resolution (ref ID -> Locator, including iframe refs)
    4. Viewport bounds validation (coordinate mode)
    5. Interaction timeout control (10 s)
    6. Ref-not-found diagnosis (URL change detection + smart suggestion generation + context ref sampling)
    7. Failure monitoring (failure rate, hot refs/actions statistics + periodic log output)

    Not responsible for: navigation, snapshot generation, content extraction, etc.
    """

    def __init__(
        self,
        page: Page,
        refs: dict[str, RefInfo],
        last_snapshot_url: str | None = None,
        humanize: HumanizeConfig | None = None,
    ):
        """Initialize Interactor

        Args:
            page: Patchright Page Instance
            refs: Ref ID -> RefInfo mapping.
            last_snapshot_url: URL from the last snapshot (used for smart diagnosis on ref failure).
            humanize: Interaction humanization config. None defaults to FAST (no humanization).
        """
        self._page = page
        self._refs = refs
        self._metrics = RefNotFoundMetrics()
        self._last_snapshot_url = last_snapshot_url
        self._humanize = humanize or HumanizeConfig()
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0

    def update_refs(
        self,
        refs: dict[str, RefInfo] | MappingProxyType[str, RefInfo],
        last_snapshot_url: str | None = None,
    ) -> None:
        """Update the refs mapping (called after each snapshot).

        Args:
            refs: New Ref ID -> RefInfo mapping (dict or MappingProxyType).
            last_snapshot_url: URL of this snapshot (for subsequent ref-failure diagnosis).
        """
        self._refs = dict(refs) if isinstance(refs, MappingProxyType) else refs
        if last_snapshot_url is not None:
            self._last_snapshot_url = last_snapshot_url

    def _get_context_refs(self, max_total: int = 15) -> list[dict[str, str]]:
        """Get a context summary of currently available refs.

        Returns a diverse sample of refs (grouped by role, preferring named refs).

        Args:
            max_total: Maximum number of refs to return.

        Returns:
            [{"ref": "e0", "role": "button", "name": "Submit"}, ...]
        """
        role_groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for ref_id, info in self._refs.items():
            role_groups[info.role].append((ref_id, info.name))

        for role, refs_list in role_groups.items():
            role_groups[role] = sorted(refs_list, key=lambda x: (not x[1], x[0]))

        result: list[dict[str, str]] = []
        per_role = max(1, max_total // max(1, len(role_groups)))

        for role in sorted(role_groups.keys()):
            for ref_id, name in role_groups[role][:per_role]:
                if len(result) >= max_total:
                    return result
                result.append({"ref": ref_id, "role": role, "name": name})

        return result

    @property
    def metrics(self) -> RefNotFoundMetrics:
        """Get ref-failure statistics data."""
        return self._metrics

    def _log_metrics_if_needed(self) -> None:
        """Periodically log failure-rate statistics (every 100 interactions)."""
        if (
            self._metrics.total_interactions % 100 == 0
            and self._metrics.total_failures > 0
        ):
            logger.info(
                "Ref failure metrics: "
                f"global_rate={self._metrics.failure_rate:.1%}, "
                f"recent_rate={self._metrics.recent_failure_rate:.1%}, "
                f"total_failures={self._metrics.total_failures}/{self._metrics.total_interactions}, "
                f"top_failed_refs={self._metrics.top_failed_refs[:3]}, "
                f"top_failed_actions={self._metrics.top_failed_actions}"
            )

    def _resolve_frame(self, ref: str) -> Page | Frame:
        """Resolve ref to the corresponding Page or Frame instance.

        If ref starts with 'f', it's an iframe ref (e.g., f1_e0).
        Otherwise it's the main page.
        """
        if ref.startswith("f"):
            parts = ref.split("_", 1)
            if len(parts) == 2:
                frame_idx_str = parts[0][1:]
                try:
                    frame_idx = int(frame_idx_str)
                    if frame_idx < len(self._page.frames):
                        return self._page.frames[frame_idx]
                except ValueError:
                    pass
        return self._page

    async def interact(self, action: str, ref: str, text: str = "") -> str:
        """Execute an element interaction.

        Args:
            action: Interaction action (click/type/fill/...).
            ref: Element ref ID (e0/e1/f1_e0/...).
            text: Interaction text (required for type/fill/press/select).

        Returns:
            Description of the interaction result.

        Raises:
            ValueError: If the action is invalid.
            RefNotFoundError: If the ref does not exist (includes structured diagnosis).
        """
        if action not in _VALID_ACTIONS:
            raise ValueError(
                f"Invalid action: {action}, must be one of {_VALID_ACTIONS}"
            )

        if ref not in self._refs:
            total_refs = len(self._refs)
            ref_ids = self._refs.keys()
            ref_range = f"{min(ref_ids)}-{max(ref_ids)}" if ref_ids else "none"
            context_refs = self._get_context_refs(max_total=15)

            self._metrics.record_interaction(failed=True, ref=ref, action=action)

            current_url = self._page.url

            logger.warning(
                "Ref not found: %s (action=%s, page=%s). "
                "Total refs: %d, Failure rate: %.1f%% "
                "(recent: %.1f%%)",
                ref,
                action,
                redact_sensitive_text(current_url)[:80],
                total_refs,
                self._metrics.failure_rate * 100,
                self._metrics.recent_failure_rate * 100,
            )

            self._log_metrics_if_needed()

            raise RefNotFoundError(
                ref=ref,
                total_refs=total_refs,
                ref_range=ref_range,
                context_refs=context_refs,
                last_snapshot_url=self._last_snapshot_url,
                context={
                    "action": action,
                    "text": text if text else None,
                    "page_url": current_url,
                },
            )

        self._metrics.record_interaction(failed=False)

        ref_info = self._refs[ref]
        frame = self._resolve_frame(ref)
        locator = resolve_locator(frame, ref_info)

        healed_msg = ""
        try:
            # Check if locator is attached. If DOM mutated significantly, this will timeout.
            await locator.wait_for(state="attached", timeout=1500)
        except Exception:
            # Attempt spatial-fingerprint self-healing
            from myrm_agent_harness.toolkits.browser.snapshot.self_healer import (
                SelfHealer,
            )

            healed_loc, new_name, _distance = await SelfHealer.heal(frame, ref_info)
            if healed_loc:
                locator = healed_loc
                healed_msg = f" [Auto-Healed to '{new_name or ref_info.name}']"
                logger.info(f"Interactor: locator for {ref} self-healed.{healed_msg}")

        from myrm_agent_harness.toolkits.browser.wait import (
            WaitStrategy,
            wait_for_page_ready,
        )

        async def _wait_after_action():
            try:
                # Wait for SPA stability after action (timeout=3000ms, quiet=500ms)
                await wait_for_page_ready(
                    self._page, strategy=WaitStrategy.SPA_STABLE, max_ms=3000
                )
            except Exception as e:
                logger.debug(f"Interactor: post-action SPA wait failed/timed out: {e}")

        try:
            if action == "click":
                if self._humanize.enable_bezier_mouse:
                    result_msg = await self._bezier_click(locator, ref, healed_msg)
                else:
                    delay = click_delay(self._humanize)
                    await locator.click(delay=delay, timeout=_INTERACTION_TIMEOUT_MS)
                    result_msg = f"Clicked {ref}{healed_msg}"
                await _wait_after_action()
                return result_msg

            elif action == "dblclick":
                delay = click_delay(self._humanize)
                await locator.dblclick(delay=delay, timeout=_INTERACTION_TIMEOUT_MS)
                await _wait_after_action()
                return f"Double-clicked {ref}{healed_msg}"

            elif action == "type":
                is_password = False
                try:
                    input_type = await locator.get_attribute("type", timeout=1000)
                    if input_type and input_type.lower() == "password":
                        is_password = True
                except Exception:
                    pass

                if is_password:
                    raise ValueError(
                        "SecurityError: Plain text typing into a password field is strictly forbidden. "
                        "You MUST use the 'fill_credential' action and provide the credential label "
                        "instead of the plain text password."
                    )

                display_text = text

                delay_per_char = type_delay(self._humanize)
                typing_timeout = max(
                    _INTERACTION_TIMEOUT_MS, len(text) * delay_per_char + 5000
                )
                await locator.type(text, delay=delay_per_char, timeout=typing_timeout)
                await _wait_after_action()
                return f"Typed '{display_text}' into {ref}{healed_msg}"

            elif action == "fill":
                is_password = False
                try:
                    input_type = await locator.get_attribute("type", timeout=1000)
                    if input_type and input_type.lower() == "password":
                        is_password = True
                except Exception:
                    pass

                if is_password:
                    raise ValueError(
                        "SecurityError: Plain text filling into a password field is strictly forbidden. "
                        "You MUST use the 'fill_credential' action and provide the credential label "
                        "instead of the plain text password."
                    )

                display_text = text

                await locator.fill(text, timeout=_INTERACTION_TIMEOUT_MS)
                await _wait_after_action()
                return f"Filled {ref} with '{display_text}'{healed_msg}"

            elif action == "fill_credential":
                from myrm_agent_harness.core.security.credential_vault import (
                    get_global_credential_vault,
                )

                vault = get_global_credential_vault()

                # Check if it's a TOTP request (e.g. label ends with -totp)
                is_totp = text.endswith("-totp")

                try:
                    if is_totp:
                        secret_text = vault.get_totp_token(text)
                    else:
                        secret_text = vault.get_password(text)
                except Exception as e:
                    raise ValueError(
                        f"Failed to retrieve credential for label '{text}': {e}"
                    ) from e

                await locator.fill(secret_text, timeout=_INTERACTION_TIMEOUT_MS)
                await _wait_after_action()
                return f"Filled credential '{text}' into {ref}{healed_msg} [CREDENTIAL_FILLED]"

            elif action == "press":
                await locator.press(text, timeout=_INTERACTION_TIMEOUT_MS)
                await _wait_after_action()
                return f"Pressed '{text}' on {ref}{healed_msg}"

            elif action == "hover":
                if self._humanize.enable_bezier_mouse:
                    if not await self._bezier_move_to(locator):
                        await locator.hover(timeout=_INTERACTION_TIMEOUT_MS)
                else:
                    await locator.hover(timeout=_INTERACTION_TIMEOUT_MS)
                return f"Hovered over {ref}{healed_msg}"

            elif action == "focus":
                await locator.focus(timeout=_INTERACTION_TIMEOUT_MS)
                return f"Focused {ref}{healed_msg}"

            elif action == "select":
                # Recorded multi-select steps join option values with "; " —
                # split them so every option is selected instead of trying to
                # match a single blob that no option equals.
                values: str | list[str] = (
                    [v.strip() for v in text.split(";")] if ";" in text else text
                )
                await locator.select_option(values, timeout=_INTERACTION_TIMEOUT_MS)
                return f"Selected '{text}' in {ref}{healed_msg}"

            elif action == "scroll":
                try:
                    delta = int(text)
                except ValueError as exc:
                    raise ValueError(
                        f"Scroll requires numeric text (pixel delta), got: {text}"
                    ) from exc

                target_x, target_y = await self._scroll_cursor_target(locator)
                await self._scroll_move_cursor(target_x, target_y)
                return await self._scroll_with_report(
                    target_x, target_y, delta, healed_msg
                )

            elif action == "scroll_to_bottom":
                params = _parse_scroll_params(text)
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
                        f"Height: {state['height']}→{state['height']}px. "
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

            elif action == "upload_file":
                await locator.set_input_files(text, timeout=_INTERACTION_TIMEOUT_MS)
                return f"Uploaded file to {ref}: {text}{healed_msg}"

            elif action == "drag":
                parts = text.split(",")
                if len(parts) != 2:
                    raise ValueError(f"Drag requires 'x,y' text, got: {text}")

                try:
                    x, y = int(parts[0]), int(parts[1])
                except ValueError as exc:
                    raise ValueError(
                        f"Drag requires numeric 'x,y', got: {text}"
                    ) from exc

                await locator.drag_to(
                    self._page.locator("body"), target_position={"x": x, "y": y}
                )
                return f"Dragged {ref} to ({x}, {y}){healed_msg}"

            elif action == "check":
                await locator.check(timeout=_INTERACTION_TIMEOUT_MS)
                return f"Checked {ref}{healed_msg}"

            elif action == "uncheck":
                await locator.uncheck(timeout=_INTERACTION_TIMEOUT_MS)
                return f"Unchecked {ref}{healed_msg}"

            return f"Unknown action: {action}"

        except Exception as e:
            error_msg = str(e)
            if (
                "TargetClosedError" in error_msg
                or "Target closed" in error_msg
                or "Timeout" in error_msg
            ):
                # This often happens when a native OS dialog (like a file picker or permission prompt)
                # blocks the browser process, causing Playwright to timeout or lose the target.

                # Check if there is ACTUALLY a dialog before injecting the hint to avoid hallucination
                has_dialog = False
                try:
                    from myrm_agent_harness.toolkits.computer_use.session import (
                        create_computer_session,
                    )
                    from myrm_agent_harness.toolkits.computer_use.types import (
                        KNOWN_BROWSER_NAMES,
                        ComputerUseConfig,
                    )

                    cu_session = create_computer_session(ComputerUseConfig())
                    has_dialog = await cu_session.backend.has_blocking_dialog(
                        list(KNOWN_BROWSER_NAMES)
                    )
                except Exception:
                    pass

                if has_dialog:
                    logger.warning(
                        f"Browser interaction failed and OS dialog detected: {e}"
                    )
                    return (
                        f"Interaction failed: {error_msg}\n\n"
                        "[CRITICAL WARNING: A native OS dialog (e.g., File Upload, Permission Request) "
                        "is currently blocking the browser. Playwright CANNOT interact with native OS dialogs. "
                        "You MUST switch to 'desktop_snapshot' and 'desktop_interact_tool' immediately to handle it.]"
                    )
                else:
                    # If no dialog is detected, it's just a regular timeout/error.
                    # Don't inject the hint to avoid confusing the agent.
                    logger.warning(
                        f"Browser interaction failed (no OS dialog detected): {e}"
                    )
            raise

    async def _bezier_move_to(self, locator: Locator) -> bool:
        """Move mouse to the locator via Bézier curve. Returns True if move succeeded."""
        await locator.wait_for(state="visible", timeout=_INTERACTION_TIMEOUT_MS)
        box = await locator.bounding_box(timeout=_INTERACTION_TIMEOUT_MS)
        if box is None:
            return False

        target_x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
        target_y = box["y"] + box["height"] * random.uniform(0.35, 0.65)

        if self._mouse_x == 0.0 and self._mouse_y == 0.0:
            viewport = self._page.viewport_size
            self._mouse_x = float((viewport or {}).get("width", 800)) / 2
            self._mouse_y = float((viewport or {}).get("height", 600)) / 2

        await bezier_move(
            self._page, self._mouse_x, self._mouse_y, target_x, target_y, self._humanize
        )
        self._mouse_x, self._mouse_y = target_x, target_y
        return True

    # ------------------------------------------------------------------
    # Scroll humanization (wheel-burst inertial scrolling)
    # ------------------------------------------------------------------

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
            await bezier_move(
                self._page, self._mouse_x, self._mouse_y, x, y, self._humanize
            )
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
        result = await self._page.evaluate(
            _SCROLL_MEASURE_JS, {"x": round(x), "y": round(y)}
        )
        return {
            "top": float(result["top"]),
            "height": float(result["height"]),
            "client": float(result["client"]),
        }

    async def _scroll_with_report(
        self, x: float, y: float, delta: int, suffix: str
    ) -> str:
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

    async def _scroll_noop_reason(
        self, x: float, y: float, before: dict[str, float], delta: int
    ) -> str:
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
            await asyncio.sleep(
                random.randint(*self._humanize.scroll_pre_move_delay) / 1000.0
            )
            direction = 1 if delta > 0 else -1
            accel, decel = scroll_phase_steps(self._humanize)
            avg_delta = (
                self._humanize.scroll_delta_base[0]
                + self._humanize.scroll_delta_base[1]
            ) / 2
            total_notches = max(accel + decel + 1, round(abs(delta) / avg_delta))
            phases = (
                ["accel"] * accel
                + ["cruise"] * max(0, total_notches - accel - decel)
                + ["decel"] * decel
            )
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
            await asyncio.sleep(
                random.randint(*self._humanize.scroll_settle_delay) / 1000.0
            )
            for _ in range(random.randint(1, 2)):
                correction = random.randint(40, 80) * -direction
                await wheel_burst(self._page, correction, self._humanize)
                await asyncio.sleep(random.randint(100, 250) / 1000.0)
        else:
            await asyncio.sleep(
                random.randint(*self._humanize.scroll_settle_delay) / 1000.0
            )

    async def _bezier_click(self, locator: Locator, ref: str, healed_msg: str) -> str:
        """Click with Bézier mouse trajectory (CAREFUL mode only).

        Uses low-level mouse API to preserve the Bézier path that locator.click()
        would overwrite with an instantaneous move.
        """
        if not await self._bezier_move_to(locator):
            delay = click_delay(self._humanize)
            await locator.click(delay=delay, timeout=_INTERACTION_TIMEOUT_MS)
            return f"Clicked {ref}{healed_msg}"

        delay_ms = click_delay(self._humanize)
        await self._page.mouse.down()
        await asyncio.sleep(delay_ms / 1000.0)
        await self._page.mouse.up()

        return f"Clicked {ref}{healed_msg}"

    # ------------------------------------------------------------------
    # Coordinate-based interaction (Visual Mode)
    # ------------------------------------------------------------------

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
