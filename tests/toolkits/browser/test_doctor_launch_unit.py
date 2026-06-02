"""Unit tests for browser launch check exception paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, _check_browser_launch

pytestmark = pytest.mark.asyncio


async def test_check_browser_launch_timeout():
    """Should handle browser launch timeout."""

    async def mock_async_playwright_context():
        mock_playwright = AsyncMock()
        mock_chromium = AsyncMock()
        mock_chromium.launch = AsyncMock(side_effect=TimeoutError("Launch timeout"))
        mock_playwright.chromium = mock_chromium
        yield mock_playwright

    mock_async_playwright = AsyncMock()
    mock_async_playwright.return_value.__aenter__ = AsyncMock(side_effect=mock_async_playwright_context)
    mock_async_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_async_playwright.return_value.start = AsyncMock(side_effect=TimeoutError("Launch timeout"))

    with patch("patchright.async_api.async_playwright", return_value=mock_async_playwright.return_value):
        result = await _check_browser_launch(launch_options=None)

    assert result.status == CheckStatus.ERROR
    assert "timeout" in result.message.lower()
    assert result.fix is not None


async def test_check_browser_launch_executable_not_found():
    """Should handle missing browser executable."""
    mock_async_playwright = AsyncMock()
    mock_async_playwright.return_value.start = AsyncMock(
        side_effect=RuntimeError("Executable doesn't exist at /nonexistent/chrome")
    )

    with patch("patchright.async_api.async_playwright", return_value=mock_async_playwright.return_value):
        result = await _check_browser_launch(launch_options=None)

    assert result.status == CheckStatus.ERROR
    assert "not found" in result.message.lower()
    assert "patchright install" in result.fix


async def test_check_browser_launch_permission_denied():
    """Should handle permission errors."""
    mock_async_playwright = AsyncMock()
    mock_async_playwright.return_value.start = AsyncMock(side_effect=RuntimeError("Permission denied: /path/to/chrome"))

    with patch("patchright.async_api.async_playwright", return_value=mock_async_playwright.return_value):
        result = await _check_browser_launch(launch_options=None)

    assert result.status == CheckStatus.ERROR
    assert "permission" in result.message.lower()
    assert "permission" in result.fix.lower()


async def test_check_browser_launch_generic_error():
    """Should handle generic launch errors."""
    mock_async_playwright = AsyncMock()
    mock_async_playwright.return_value.start = AsyncMock(side_effect=RuntimeError("Unknown launch error"))

    with patch("patchright.async_api.async_playwright", return_value=mock_async_playwright.return_value):
        result = await _check_browser_launch(launch_options=None)

    assert result.status == CheckStatus.ERROR
    assert "failed" in result.message.lower()
    assert result.fix is not None
