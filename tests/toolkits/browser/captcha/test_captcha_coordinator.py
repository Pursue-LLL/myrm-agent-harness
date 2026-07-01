"""Tests for CaptchaCoordinator state machine."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.captcha.coordinator import CaptchaCoordinator
from myrm_agent_harness.toolkits.browser.captcha.protocols import (
    CaptchaInfo,
    CaptchaSolveResult,
    CaptchaStatus,
    CaptchaType,
)


def _make_info() -> CaptchaInfo:
    return CaptchaInfo(
        captcha_type=CaptchaType.CLOUDFLARE_CHALLENGE,
        reason="Cloudflare challenge form",
    )


def _make_mock_page() -> MagicMock:
    """Create a mock that passes isinstance(page, PatchrightPage)."""
    from patchright.async_api import Page as PatchrightPage

    page = MagicMock(spec=PatchrightPage)
    return page


def _make_solver(
    success: bool = True,
    elapsed_ms: float = 5000.0,
    delay: float = 0.0,
) -> MagicMock:
    """Create a mock CaptchaSolver."""
    result = CaptchaSolveResult(
        success=success,
        method="mock",
        elapsed_ms=elapsed_ms,
    )

    async def solve(captcha_info: CaptchaInfo, page: object) -> CaptchaSolveResult:
        if delay > 0:
            await asyncio.sleep(delay)
        return result

    solver = MagicMock()
    solver.solve = AsyncMock(side_effect=solve)
    return solver


class TestCoordinatorInit:
    """Initialization tests."""

    def test_default_status_is_none(self) -> None:
        solver = _make_solver()
        coord = CaptchaCoordinator(solver)
        assert coord.status == CaptchaStatus.NONE
        assert coord.last_info is None

    def test_custom_timeout(self) -> None:
        solver = _make_solver()
        coord = CaptchaCoordinator(solver, solve_timeout=60.0)
        assert coord._solve_timeout == 60.0


class TestCoordinatorHandleCaptcha:
    """handle_captcha state machine tests."""

    @pytest.mark.asyncio
    async def test_successful_solve(self) -> None:
        solver = _make_solver(success=True)
        coord = CaptchaCoordinator(solver)
        info = _make_info()
        page = _make_mock_page()

        with patch(
            "myrm_agent_harness.toolkits.browser.captcha.coordinator.CaptchaCoordinator._publish_event",
            new_callable=AsyncMock,
        ) as mock_publish:
            result = await coord.handle_captcha(info, page)

        assert result.success is True
        assert coord.status == CaptchaStatus.RESOLVED
        assert coord.last_info is info

        published_events = [call.args[0] for call in mock_publish.call_args_list]
        assert "captcha_detected" in published_events
        assert "captcha_resolved" in published_events

    @pytest.mark.asyncio
    async def test_successful_solve_dispatches_takeover_completed(self) -> None:
        solver = _make_solver(success=True, elapsed_ms=3200.0)
        coord = CaptchaCoordinator(solver)
        info = _make_info()
        page = _make_mock_page()

        with (
            patch(
                "myrm_agent_harness.toolkits.browser.captcha.coordinator.CaptchaCoordinator._publish_event",
                new_callable=AsyncMock,
            ),
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ) as mock_dispatch,
        ):
            result = await coord.handle_captcha(info, page)

        assert result.success is True
        dispatch_calls = [
            (c.args[0], c.args[1]) for c in mock_dispatch.call_args_list
        ]
        takeover_completed = [
            payload for event, payload in dispatch_calls
            if event == "browser_takeover_completed"
        ]
        assert len(takeover_completed) == 1
        assert takeover_completed[0]["elapsed_ms"] == 3200.0
        assert takeover_completed[0]["success"] is True

    @pytest.mark.asyncio
    async def test_failed_solve_dispatches_takeover_completed_with_success_false(self) -> None:
        solver = _make_solver(success=False)
        coord = CaptchaCoordinator(solver)
        page = _make_mock_page()

        with (
            patch(
                "myrm_agent_harness.toolkits.browser.captcha.coordinator.CaptchaCoordinator._publish_event",
                new_callable=AsyncMock,
            ),
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ) as mock_dispatch,
        ):
            await coord.handle_captcha(_make_info(), page)

        dispatch_calls = [
            (c.args[0], c.args[1]) for c in mock_dispatch.call_args_list
        ]
        takeover_completed = [
            payload for event, payload in dispatch_calls
            if event == "browser_takeover_completed"
        ]
        assert len(takeover_completed) == 1
        assert takeover_completed[0]["success"] is False

    @pytest.mark.asyncio
    async def test_failed_solve(self) -> None:
        solver = _make_solver(success=False)
        coord = CaptchaCoordinator(solver)
        page = _make_mock_page()

        with patch(
            "myrm_agent_harness.toolkits.browser.captcha.coordinator.CaptchaCoordinator._publish_event",
            new_callable=AsyncMock,
        ):
            result = await coord.handle_captcha(_make_info(), page)

        assert result.success is False
        assert coord.status == CaptchaStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        solver = _make_solver(delay=5.0)
        coord = CaptchaCoordinator(solver, solve_timeout=0.1)
        page = _make_mock_page()

        with patch(
            "myrm_agent_harness.toolkits.browser.captcha.coordinator.CaptchaCoordinator._publish_event",
            new_callable=AsyncMock,
        ) as mock_publish:
            result = await coord.handle_captcha(_make_info(), page)

        assert result.success is False
        assert result.method == "timeout"
        assert coord.status == CaptchaStatus.TIMEOUT

        published_events = [call.args[0] for call in mock_publish.call_args_list]
        assert "captcha_timeout" in published_events

    @pytest.mark.asyncio
    async def test_solver_exception(self) -> None:
        solver = MagicMock()
        solver.solve = AsyncMock(side_effect=RuntimeError("Solver crashed"))
        coord = CaptchaCoordinator(solver)
        page = _make_mock_page()

        with patch(
            "myrm_agent_harness.toolkits.browser.captcha.coordinator.CaptchaCoordinator._publish_event",
            new_callable=AsyncMock,
        ):
            result = await coord.handle_captcha(_make_info(), page)

        assert result.success is False
        assert result.method == "error"
        assert "Solver crashed" in result.message
        assert coord.status == CaptchaStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_wrong_page_type_raises_typeerror(self) -> None:
        solver = _make_solver()
        coord = CaptchaCoordinator(solver)
        with pytest.raises(TypeError, match="Expected PatchrightPage"):
            await coord.handle_captcha(_make_info(), "not_a_page")  # type: ignore[arg-type]


class TestCoordinatorReset:
    """reset() state tests."""

    @pytest.mark.asyncio
    async def test_reset_clears_state(self) -> None:
        solver = _make_solver()
        coord = CaptchaCoordinator(solver)
        page = _make_mock_page()

        with patch(
            "myrm_agent_harness.toolkits.browser.captcha.coordinator.CaptchaCoordinator._publish_event",
            new_callable=AsyncMock,
        ):
            await coord.handle_captcha(_make_info(), page)

        assert coord.status != CaptchaStatus.NONE
        coord.reset()
        assert coord.status == CaptchaStatus.NONE
        assert coord.last_info is None
