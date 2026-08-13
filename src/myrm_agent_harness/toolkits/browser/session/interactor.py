"""Element interaction — single responsibility.

[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)
- snapshot::RefInfo (POS: element ref metadata)
- snapshot::resolve_locator (POS: rebuild Locator from RefInfo)
- exceptions::RefNotFoundError (POS: structured ref-not-found exception)
- pool.config::HumanizeConfig (POS: interaction humanization config)
- session.humanize::click_delay, type_delay, bezier_move (POS: humanized delay and Bézier mouse helpers)
- session.interactor_scroll_mixin::ScrollHumanizeMixin (POS: humanized wheel-input scrolling behaviors)
- session.interactor_coord_mixin::CoordInteractMixin (POS: coordinate-based Visual Mode interactions)
- session.ref_metrics::RefNotFoundMetrics, RefDiagnosticsMixin (POS: ref failure statistics + diagnosis behaviors)

[OUTPUT]
- Interactor: element interaction manager (supports humanized delays + Bézier mouse via HumanizeConfig)

[POS]
Element interaction manager. Responsibilities:
1. Ref-based operations (15 actions: click/dblclick/type/fill/fill_credential/press/hover/focus/select/scroll/scroll_to_bottom/upload_file/drag/check/uncheck)
2. Ref resolution (from ref ID to Locator, supports iframe refs)
3. Interaction timeout control (10s)
4. Ref failure diagnosis (URL change detection + smart suggestion generation + context refs sampling)
5. Failure monitoring (failure rate, hot refs, hot actions statistics + periodic log output)

Ref interaction dispatch and Bézier clicks live here; humanized scrolling
(wheel-burst delivery, honest reporting, pre-interaction target centering) and
coordinate interactions (interact_at) are provided by ScrollHumanizeMixin and
CoordInteractMixin respectively. Single responsibility: only handles element
interaction logic; does not handle navigation, snapshot, extraction, etc.
Tab-level URL state is managed by TabController.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from types import MappingProxyType
from typing import TYPE_CHECKING

from myrm_agent_harness.core.security.redact import redact_sensitive_text
from myrm_agent_harness.toolkits.browser.exceptions import (
    ClickTargetUnreachableError,
    RefNotFoundError,
)
from myrm_agent_harness.toolkits.browser.pool.config import HumanizeConfig
from myrm_agent_harness.toolkits.browser.session.humanize import (
    bezier_move,
    click_delay,
    type_delay,
)
from myrm_agent_harness.toolkits.browser.session.interactor_coord_mixin import (
    CoordInteractMixin,
)
from myrm_agent_harness.toolkits.browser.session.interactor_scroll_mixin import (
    ScrollHumanizeMixin,
    _parse_scroll_params,
)
from myrm_agent_harness.toolkits.browser.session.ref_metrics import (
    RefDiagnosticsMixin,
    RefNotFoundMetrics,
)
from myrm_agent_harness.toolkits.browser.snapshot import resolve_locator

if TYPE_CHECKING:
    from patchright.async_api import Frame, Locator, Page

    from myrm_agent_harness.toolkits.browser.snapshot import RefInfo

logger = logging.getLogger(__name__)


_INTERACTION_TIMEOUT_MS = 10_000
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


class Interactor(ScrollHumanizeMixin, CoordInteractMixin, RefDiagnosticsMixin):
    """Element interaction manager — single responsibility.

    Responsibilities:
    1. Ref-based actions (15 types: click/dblclick/type/fill/fill_credential/press/hover/focus/select/scroll/scroll_to_bottom/upload_file/drag/check/uncheck)
    2. Ref resolution (ref ID -> Locator, including iframe refs)
    3. Interaction timeout control (10 s)
    4. Ref-not-found diagnosis (URL change detection + smart suggestion generation + context ref sampling)
    5. Failure monitoring (failure rate, hot refs/actions statistics + periodic log output)

    Scrolling (wheel-burst inertial delivery, honest reporting, CAREFUL
    pre-interaction target centering), coordinate interactions (interact_at),
    and ref-failure diagnosis (`_get_context_refs`/`_log_metrics_if_needed`)
    are inherited from ScrollHumanizeMixin, CoordInteractMixin, and
    RefDiagnosticsMixin.

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

        # CAREFUL-only: bring the target into the viewport center band with the same
        # humanized wheel stack used by explicit scrolls, instead of Playwright's
        # implicit one-shot scrollIntoViewIfNeeded (instant JS jump, CDP fingerprint).
        # Scroll actions own their own positioning, so they are excluded.
        if self._humanize.enable_bezier_mouse and action not in (
            "scroll",
            "scroll_to_bottom",
        ):
            await self._ensure_target_in_view(locator)

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
        # "attached" not "visible": patchright's visible semantics reject elements
        # clipped by an iframe viewport even after they were scrolled into it, and
        # the off-viewport check below is the real reachability gate anyway.
        await locator.wait_for(state="attached", timeout=_INTERACTION_TIMEOUT_MS)
        box = await locator.bounding_box(timeout=_INTERACTION_TIMEOUT_MS)
        if box is None:
            return False

        target_x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
        target_y = box["y"] + box["height"] * random.uniform(0.35, 0.65)

        viewport = self._page.viewport_size or {"width": 1280, "height": 720}
        vw, vh = float(viewport["width"]), float(viewport["height"])
        # CDP clamps off-viewport mouse coordinates to the viewport edge, so moving
        # to a target whose center is still outside the viewport would make the
        # mouse.down/up land on the edge and miss silently. Hand the interaction back
        # to the native locator action instead: its scrollIntoViewIfNeeded either
        # scrolls the target in, or fails loudly — never a silent wrong click.
        if not (0.0 <= target_x <= vw and 0.0 <= target_y <= vh):
            return False

        if self._mouse_x == 0.0 and self._mouse_y == 0.0:
            self._mouse_x = vw / 2
            self._mouse_y = vh / 2

        await bezier_move(
            self._page, self._mouse_x, self._mouse_y, target_x, target_y, self._humanize
        )
        self._mouse_x, self._mouse_y = target_x, target_y
        return True

    async def _guard_native_click(self, locator: Locator) -> None:
        """Refuse a native click that could only silently miss.

        After the humanized pre-scroll, an off-viewport target with no
        wheel-scrollable ancestor (e.g. body overflow:hidden) cannot be brought
        in — the native locator.click would clamp the pointer to the viewport
        edge and report success while hitting nothing. Fail loudly instead.
        Targets with a scroll path, or targets the probe cannot measure, still
        fall through to the native click (its scrollIntoViewIfNeeded can help).
        """
        probe = await self._target_probe(locator)
        if probe is None:
            return
        if not probe["visible"] and not probe.get("container"):
            raise ClickTargetUnreachableError(
                "Click target is outside the viewport and no scrollable "
                "container exists to bring it in (locked scroll). Refusing to "
                "click at the viewport edge."
            )

    async def _bezier_click(self, locator: Locator, ref: str, healed_msg: str) -> str:
        """Click with Bézier mouse trajectory (CAREFUL mode only).

        Uses low-level mouse API to preserve the Bézier path that locator.click()
        would overwrite with an instantaneous move.
        """
        if not await self._bezier_move_to(locator):
            await self._guard_native_click(locator)
            delay = click_delay(self._humanize)
            await locator.click(delay=delay, timeout=_INTERACTION_TIMEOUT_MS)
            return f"Clicked {ref}{healed_msg}"

        delay_ms = click_delay(self._humanize)
        await self._page.mouse.down()
        await asyncio.sleep(delay_ms / 1000.0)
        await self._page.mouse.up()

        return f"Clicked {ref}{healed_msg}"
