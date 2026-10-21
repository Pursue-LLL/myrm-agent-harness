"""Chain-of-responsibility CAPTCHA solver.

Attempts the primary solver first (typically ApiSolver), falling back to
a secondary solver (typically ManualSolver) on failure.

[INPUT]
- .protocols::CaptchaInfo, CaptchaSolveResult, CaptchaSolver (POS: types/protocol)

[OUTPUT]
- FallbackSolver: chain-of-responsibility CaptchaSolver implementation

[POS]
Composite CAPTCHA solver with automatic failover.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .protocols import CaptchaInfo, CaptchaSolveResult

if TYPE_CHECKING:
    from patchright.async_api import Page

    from .protocols import CaptchaSolver

logger = logging.getLogger(__name__)


class FallbackSolver:
    """Try a primary solver first, fall back to secondary on failure.

    Thread-safety: stateless — safe for concurrent use (delegates to solvers).
    """

    def __init__(self, primary: CaptchaSolver, fallback: CaptchaSolver) -> None:
        self._primary = primary
        self._fallback = fallback

    async def solve(
        self,
        captcha_info: CaptchaInfo,
        page: Page,
    ) -> CaptchaSolveResult:
        """Attempt primary solver, then fallback if primary fails."""
        result = await self._primary.solve(captcha_info, page)
        if result.success:
            return result

        logger.info(
            "FallbackSolver: primary solver failed (%s), trying fallback",
            result.message,
        )
        return await self._fallback.solve(captcha_info, page)
