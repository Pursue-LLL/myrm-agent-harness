"""Tests for ManualSolver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.captcha.manual_solver import ManualSolver
from myrm_agent_harness.toolkits.browser.captcha.protocols import (
    CaptchaInfo,
    CaptchaType,
)


def _make_info() -> CaptchaInfo:
    return CaptchaInfo(
        captcha_type=CaptchaType.CLOUDFLARE_CHALLENGE,
        reason="test challenge",
    )


class TestManualSolver:
    """ManualSolver tests."""

    @pytest.mark.asyncio
    async def test_solve_success_on_first_poll(self) -> None:
        """CAPTCHA disappears after first poll."""
        solver = ManualSolver()
        page = MagicMock()

        with patch(
            "myrm_agent_harness.toolkits.browser.captcha.detector.detect_captcha",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "myrm_agent_harness.toolkits.browser.captcha.manual_solver._POLL_INTERVAL_S",
            0.01,
        ):
            result = await solver.solve(_make_info(), page)

        assert result.success is True
        assert result.method == "manual"
        assert result.elapsed_ms > 0

    @pytest.mark.asyncio
    async def test_solve_success_after_multiple_polls(self) -> None:
        """CAPTCHA disappears after 3 polls."""
        solver = ManualSolver()
        page = MagicMock()

        call_count = 0
        still_blocked = CaptchaInfo(
            captcha_type=CaptchaType.CLOUDFLARE_CHALLENGE,
            reason="still there",
        )

        async def mock_detect(_page: object) -> CaptchaInfo | None:
            nonlocal call_count
            call_count += 1
            return None if call_count >= 3 else still_blocked

        with patch(
            "myrm_agent_harness.toolkits.browser.captcha.detector.detect_captcha",
            side_effect=mock_detect,
        ), patch(
            "myrm_agent_harness.toolkits.browser.captcha.manual_solver._POLL_INTERVAL_S",
            0.01,
        ):
            result = await solver.solve(_make_info(), page)

        assert result.success is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_solve_failure_max_polls_exhausted(self) -> None:
        """CAPTCHA never disappears, max polls reached."""
        solver = ManualSolver()
        page = MagicMock()
        still_blocked = CaptchaInfo(
            captcha_type=CaptchaType.CLOUDFLARE_CHALLENGE,
            reason="stuck",
        )

        with patch(
            "myrm_agent_harness.toolkits.browser.captcha.detector.detect_captcha",
            new_callable=AsyncMock,
            return_value=still_blocked,
        ), patch(
            "myrm_agent_harness.toolkits.browser.captcha.manual_solver._POLL_INTERVAL_S",
            0.01,
        ), patch(
            "myrm_agent_harness.toolkits.browser.captcha.manual_solver._MAX_POLLS",
            3,
        ):
            result = await solver.solve(_make_info(), page)

        assert result.success is False
        assert result.method == "manual"
        assert "did not solve" in result.message.lower()
