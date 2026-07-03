"""Shared fixtures for browser integration tests."""

from __future__ import annotations

import asyncio
import atexit

import pytest

try:
    from patchright.async_api import Browser, BrowserContext, async_playwright
except ImportError:
    Browser = None  # type: ignore[misc, assignment]
    BrowserContext = None  # type: ignore[misc, assignment]
    async_playwright = None  # type: ignore[misc, assignment]

_shared_playwright = None
_shared_browser = None
_shared_context = None


@pytest.fixture(scope="session")
def browser_context():
    """Shared browser context for all integration tests.

    Uses patchright directly for simplicity and reliability.
    Avoids GlobalBrowserPool which may be slow in test environments.
    """
    if async_playwright is None:
        pytest.skip("patchright not installed")

    global _shared_playwright, _shared_browser, _shared_context

    async def setup():
        global _shared_playwright, _shared_browser, _shared_context
        _shared_playwright = await async_playwright().start()
        _shared_browser = await _shared_playwright.chromium.launch(headless=True)
        _shared_context = await _shared_browser.new_context()

    async def teardown():
        global _shared_browser, _shared_playwright
        if _shared_context:
            await _shared_context.close()
        if _shared_browser:
            await _shared_browser.close()
        if _shared_playwright:
            await _shared_playwright.stop()

    asyncio.run(setup())
    yield _shared_context
    asyncio.run(teardown())


def _cleanup_browser_child_processes() -> None:
    from tests.support.browser_process_cleanup import terminate_browser_processes_in_tree

    terminate_browser_processes_in_tree()


atexit.register(_cleanup_browser_child_processes)
