"""Manual CAPTCHA solver — default framework implementation.

Publishes a ``captcha_detected`` event so the frontend can notify the user,
then polls the page until the CAPTCHA disappears (indicating the user solved
it manually in the browser window).

This solver is always available and requires no third-party service.

[INPUT]
- .protocols::CaptchaInfo, CaptchaSolveResult (POS: data types)
- .detector::detect_captcha (POS: re-check after user action)

[OUTPUT]
- ManualSolver: default CaptchaSolver implementation

[POS]
Manual (human-in-the-loop) CAPTCHA solver for browser automation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .protocols import CaptchaInfo, CaptchaSolveResult

if TYPE_CHECKING:
    from patchright.async_api import Page

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 2.0
_MAX_POLLS = 60


class ManualSolver:
    """Human-in-the-loop CAPTCHA solver.

    Waits for the user to solve the CAPTCHA in the browser window by
    periodically re-checking whether the CAPTCHA page has been replaced
    with normal content.

    Works in all deployment modes:
    - **Local WebUI / Tauri**: User sees the browser window directly.
    - **SaaS**: User connects via VNC/noVNC to the sandboxed browser.

    The frontend receives a ``captcha_detected`` event and displays a
    status card guiding the user.
    """

    async def solve(
        self,
        captcha_info: CaptchaInfo,
        page: Page,
    ) -> CaptchaSolveResult:
        """Poll until the CAPTCHA disappears or max polls are exhausted.

        Args:
            captcha_info: Metadata about the detected CAPTCHA.
            page: The Patchright page containing the CAPTCHA.

        Returns:
            Success if the CAPTCHA page is no longer detected.
        """
        from .detector import detect_captcha

        start = time.monotonic()

        logger.info(
            "ManualSolver: waiting for user to solve %s CAPTCHA",
            captcha_info.captcha_type.value,
        )

        for poll in range(_MAX_POLLS):
            await asyncio.sleep(_POLL_INTERVAL_S)

            still_blocked = await detect_captcha(page)
            if still_blocked is None:
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.info(
                    "ManualSolver: CAPTCHA resolved by user (polls=%d, elapsed=%.0fms)",
                    poll + 1,
                    elapsed_ms,
                )
                return CaptchaSolveResult(
                    success=True,
                    method="manual",
                    elapsed_ms=elapsed_ms,
                )

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.warning(
            "ManualSolver: max polls (%d) exhausted, CAPTCHA not resolved (elapsed=%.0fms)",
            _MAX_POLLS,
            elapsed_ms,
        )
        return CaptchaSolveResult(
            success=False,
            method="manual",
            elapsed_ms=elapsed_ms,
            message=f"User did not solve CAPTCHA within {_MAX_POLLS * _POLL_INTERVAL_S:.0f}s",
        )
