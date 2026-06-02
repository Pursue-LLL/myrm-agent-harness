"""CAPTCHA coordination — pause/resume Agent execution.

Manages the state machine for CAPTCHA detection → solving → resolution,
using ``asyncio.Event`` to block the navigate call until the CAPTCHA is
resolved or the timeout fires.

[INPUT]
- .protocols::CaptchaInfo, CaptchaSolveResult, CaptchaSolver, CaptchaStatus
- utils.event_utils::dispatch_custom_event (POS: event dispatch)

[OUTPUT]
- CaptchaCoordinator: stateful coordinator (one per BrowserSession)

[POS]
CAPTCHA coordination for browser automation sessions.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .protocols import CaptchaInfo, CaptchaSolveResult, CaptchaStatus

if TYPE_CHECKING:
    from .protocols import CaptchaSolver

logger = logging.getLogger(__name__)

_DEFAULT_SOLVE_TIMEOUT_S = 120.0


class CaptchaCoordinator:
    """Coordinate CAPTCHA detection, solving, and Agent pause/resume.

    Lifecycle (per navigation):
        1. ``handle_captcha()`` is called when a blocking CAPTCHA is detected.
        2. The coordinator transitions NONE → DETECTED → SOLVING.
        3. It delegates to the configured ``CaptchaSolver``.
        4. On success → RESOLVED; on timeout → TIMEOUT.

    Thread-safety: single-task usage within one ``BrowserSession``.
    """

    def __init__(
        self,
        solver: CaptchaSolver,
        *,
        solve_timeout: float = _DEFAULT_SOLVE_TIMEOUT_S,
    ) -> None:
        """
        Args:
            solver: Pluggable CAPTCHA solver implementation.
            solve_timeout: Max seconds to wait for CAPTCHA resolution.
        """
        self._solver = solver
        self._solve_timeout = solve_timeout
        self._status = CaptchaStatus.NONE
        self._last_info: CaptchaInfo | None = None

    @property
    def status(self) -> CaptchaStatus:
        return self._status

    @property
    def last_info(self) -> CaptchaInfo | None:
        return self._last_info

    async def handle_captcha(
        self,
        captcha_info: CaptchaInfo,
        page: object,
    ) -> CaptchaSolveResult:
        """Handle a detected CAPTCHA: solve it and return the result.

        This method blocks until the CAPTCHA is solved or the timeout fires.
        The caller (``BrowserSession.navigate``) awaits this before returning.

        Args:
            captcha_info: Detection metadata.
            page: Patchright Page instance (typed as object to avoid import).

        Returns:
            Solve result with success/failure and diagnostics.
        """
        from patchright.async_api import Page as PatchrightPage

        if not isinstance(page, PatchrightPage):
            raise TypeError(f"Expected PatchrightPage, got {type(page).__name__}")

        self._status = CaptchaStatus.DETECTED
        self._last_info = captcha_info

        await self._publish_event("captcha_detected", captcha_info)

        self._status = CaptchaStatus.SOLVING
        start = time.monotonic()

        try:
            result = await asyncio.wait_for(
                self._solver.solve(captcha_info, page),
                timeout=self._solve_timeout,
            )
        except TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._status = CaptchaStatus.TIMEOUT
            result = CaptchaSolveResult(
                success=False,
                method="timeout",
                elapsed_ms=elapsed_ms,
                message=f"CAPTCHA solve timed out after {self._solve_timeout:.0f}s",
            )
            logger.warning(
                "CAPTCHA solve timed out: %s (elapsed=%.0fms)",
                captcha_info.reason,
                elapsed_ms,
            )
            await self._publish_event("captcha_timeout", captcha_info)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._status = CaptchaStatus.TIMEOUT
            result = CaptchaSolveResult(
                success=False,
                method="error",
                elapsed_ms=elapsed_ms,
                message=f"CAPTCHA solve error: {exc}",
            )
            logger.error(
                "CAPTCHA solve error: %s (reason=%s, elapsed=%.0fms)",
                exc,
                captcha_info.reason,
                elapsed_ms,
            )
            await self._publish_event("captcha_timeout", captcha_info)
        else:
            if result.success:
                self._status = CaptchaStatus.RESOLVED
                logger.info(
                    "CAPTCHA resolved: %s via %s (elapsed=%.0fms)",
                    captcha_info.reason,
                    result.method,
                    result.elapsed_ms,
                )
                await self._publish_event("captcha_resolved", captcha_info)
            else:
                self._status = CaptchaStatus.TIMEOUT
                logger.warning(
                    "CAPTCHA solve failed: %s via %s — %s",
                    captcha_info.reason,
                    result.method,
                    result.message,
                )
                await self._publish_event("captcha_timeout", captcha_info)

        return result

    def reset(self) -> None:
        """Reset coordinator state for the next navigation."""
        self._status = CaptchaStatus.NONE
        self._last_info = None

    async def _publish_event(self, event_name: str, captcha_info: CaptchaInfo) -> None:
        """Publish a CAPTCHA event via the framework event system."""
        try:
            from myrm_agent_harness.utils.event_utils import dispatch_custom_event

            await dispatch_custom_event(
                event_name,
                {
                    "captcha_type": captcha_info.captcha_type.value,
                    "reason": captcha_info.reason,
                    "blocking": captcha_info.blocking,
                    "status": self._status.value,
                },
            )
        except Exception as exc:
            logger.debug("Failed to publish CAPTCHA event %s: %s", event_name, exc)
