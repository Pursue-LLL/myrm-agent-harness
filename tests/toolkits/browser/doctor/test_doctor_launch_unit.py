"""Unit tests for browser launch check exception paths."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, DoctorCheckResult
from myrm_agent_harness.toolkits.browser.doctor.launch_check import check_browser_launch

pytestmark = pytest.mark.asyncio


async def test_check_browser_launch_timeout() -> None:
    """Should handle browser launch timeout."""

    async def mock_async_playwright_context() -> AsyncIterator[AsyncMock]:
        mock_playwright = AsyncMock()
        mock_chromium = AsyncMock()
        mock_chromium.launch = AsyncMock(side_effect=TimeoutError("Launch timeout"))
        mock_playwright.chromium = mock_chromium
        yield mock_playwright

    mock_async_playwright = AsyncMock()
    mock_async_playwright.return_value.__aenter__ = AsyncMock(side_effect=mock_async_playwright_context)
    mock_async_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_async_playwright.return_value.start = AsyncMock(side_effect=TimeoutError("Launch timeout"))

    with patch(
        "patchright.async_api.async_playwright",
        return_value=mock_async_playwright.return_value,
    ):
        result = await check_browser_launch(launch_options=None)

    assert result.status == CheckStatus.ERROR
    assert "timed out" in result.message.lower()
    assert result.fix is not None


async def test_check_browser_launch_patchright_timeout() -> None:
    """Should handle patchright's TimeoutError (distinct from builtins.TimeoutError)."""
    from patchright.async_api import TimeoutError as PlaywrightTimeoutError

    mock_async_playwright = AsyncMock()
    mock_async_playwright.return_value.start = AsyncMock(side_effect=PlaywrightTimeoutError("Launch timeout"))

    with patch(
        "patchright.async_api.async_playwright",
        return_value=mock_async_playwright.return_value,
    ):
        result = await check_browser_launch(launch_options=None)

    assert result.status == CheckStatus.ERROR
    assert "timed out" in result.message.lower()
    assert result.fix is not None


async def test_check_browser_launch_executable_not_found() -> None:
    """Should handle missing browser executable."""
    mock_async_playwright = AsyncMock()
    mock_async_playwright.return_value.start = AsyncMock(
        side_effect=RuntimeError("Executable doesn't exist at /nonexistent/chrome")
    )

    with patch(
        "patchright.async_api.async_playwright",
        return_value=mock_async_playwright.return_value,
    ):
        result = await check_browser_launch(launch_options=None)

    assert result.status == CheckStatus.ERROR
    assert "not found" in result.message.lower()
    assert result.fix is not None
    assert "patchright install" in result.fix


async def test_check_browser_launch_permission_denied() -> None:
    """Should handle permission errors."""
    mock_async_playwright = AsyncMock()
    mock_async_playwright.return_value.start = AsyncMock(side_effect=RuntimeError("Permission denied: /path/to/chrome"))

    with patch(
        "patchright.async_api.async_playwright",
        return_value=mock_async_playwright.return_value,
    ):
        result = await check_browser_launch(launch_options=None)

    assert result.status == CheckStatus.ERROR
    assert "permission" in result.message.lower()
    assert result.fix is not None
    assert "permission" in result.fix.lower()


async def test_check_browser_launch_generic_error() -> None:
    """Should handle generic launch errors."""
    mock_async_playwright = AsyncMock()
    mock_async_playwright.return_value.start = AsyncMock(side_effect=RuntimeError("Unknown launch error"))

    with patch(
        "patchright.async_api.async_playwright",
        return_value=mock_async_playwright.return_value,
    ):
        result = await check_browser_launch(launch_options=None)

    assert result.status == CheckStatus.ERROR
    assert "failed" in result.message.lower()
    assert result.fix is not None


@pytest.mark.asyncio
async def test_check_browser_launch_timeout_graceful() -> None:
    """A hung launch probe must degrade to a graceful ERROR within the timeout."""

    async def never_finishes(
        _launch_opts: dict[str, object],
        _async_playwright: object,
    ) -> DoctorCheckResult:
        await asyncio.sleep(60)
        raise AssertionError("probe should have been cancelled by the timeout")

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.launch_check._LAUNCH_TIMEOUT_S",
            0.05,
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.launch_check._probe_browser_launch",
            side_effect=never_finishes,
        ),
    ):
        result = await check_browser_launch()

    assert result.status == CheckStatus.ERROR
    assert "patchright not available" not in result.message
    assert "timed out" in result.message.lower()
    assert not result.message.endswith(":")


@pytest.mark.asyncio
async def test_check_browser_launch_patchright_missing() -> None:
    """Launch check reports ERROR when patchright is not installed."""

    with patch.dict(
        "sys.modules",
        {"patchright": None, "patchright.async_api": None},
    ):
        result = await check_browser_launch()

    assert result.status == CheckStatus.ERROR
    assert "patchright not available" in result.message
