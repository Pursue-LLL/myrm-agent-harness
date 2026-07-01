"""Tests for FallbackSolver — chain-of-responsibility CAPTCHA solver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.captcha.fallback_solver import FallbackSolver
from myrm_agent_harness.toolkits.browser.captcha.protocols import (
    CaptchaInfo,
    CaptchaSolveResult,
    CaptchaType,
)


def _make_info() -> CaptchaInfo:
    return CaptchaInfo(captcha_type=CaptchaType.RECAPTCHA, reason="Test")


def _make_solver(success: bool, method: str = "mock") -> MagicMock:
    result = CaptchaSolveResult(success=success, method=method, elapsed_ms=100.0)
    solver = MagicMock()
    solver.solve = AsyncMock(return_value=result)
    return solver


class TestFallbackSolverPrimarySuccess:
    """When primary solver succeeds, fallback is never called."""

    @pytest.mark.asyncio
    async def test_primary_success_returns_immediately(self) -> None:
        primary = _make_solver(success=True, method="api")
        fallback = _make_solver(success=True, method="manual")

        solver = FallbackSolver(primary=primary, fallback=fallback)
        result = await solver.solve(_make_info(), MagicMock())

        assert result.success is True
        assert result.method == "api"
        primary.solve.assert_called_once()
        fallback.solve.assert_not_called()


class TestFallbackSolverPrimaryFails:
    """When primary solver fails, fallback is invoked."""

    @pytest.mark.asyncio
    async def test_fallback_invoked_on_primary_failure(self) -> None:
        primary = _make_solver(success=False, method="api")
        fallback = _make_solver(success=True, method="manual")

        solver = FallbackSolver(primary=primary, fallback=fallback)
        result = await solver.solve(_make_info(), MagicMock())

        assert result.success is True
        assert result.method == "manual"
        primary.solve.assert_called_once()
        fallback.solve.assert_called_once()

    @pytest.mark.asyncio
    async def test_both_fail_returns_fallback_result(self) -> None:
        primary = _make_solver(success=False, method="api")
        fallback = _make_solver(success=False, method="manual")

        solver = FallbackSolver(primary=primary, fallback=fallback)
        result = await solver.solve(_make_info(), MagicMock())

        assert result.success is False
        assert result.method == "manual"
        primary.solve.assert_called_once()
        fallback.solve.assert_called_once()
