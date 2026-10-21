"""Real-browser integration tests for ActionCaptureEngine navigation resilience.

Regression tests for the world-isolation bug where capture silently stopped
after a navigation: `add_init_script` targets the main world while
`page.evaluate` defaults to the isolated world, and the main-world context is
only materialized lazily after navigation. The engine now re-injects listeners
via `evaluate` on `framenavigated`, so:

1. capture keeps working after a navigation (S3)
2. stop/pause/resume always control exactly the listeners that emit (S4)
3. restarting a session never double-records a single interaction (S5)

Run with: pytest -m integration
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Any

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.asyncio,
]

from myrm_agent_harness.toolkits.browser.action_capture.capture_engine import (
    ActionCaptureEngine,
)


class _Collector:
    def __init__(self) -> None:
        self.steps: list[tuple[str, str]] = []

    async def on_step(self, step: Any) -> None:
        self.steps.append((step.action.value, step.selector))


@pytest.fixture(scope="module")
def page_urls(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, str]:
    """Two static pages served over HTTP on 127.0.0.1."""
    tmp = tmp_path_factory.mktemp("capture_pages")
    (tmp / "p1.html").write_text("<html><body><button id='b'>p1</button></body></html>", encoding="utf-8")
    (tmp / "p2.html").write_text("<html><body><button id='b'>p2</button></body></html>", encoding="utf-8")
    server = HTTPServer(
        ("127.0.0.1", 0),
        lambda *a, **k: SimpleHTTPRequestHandler(*a, directory=str(tmp), **k),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    yield f"{base}/p1.html", f"{base}/p2.html"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture
async def capture_harness(page_urls: tuple[str, str]) -> AsyncIterator[Any]:
    """Real Chromium page wired to an ActionCaptureEngine."""
    from patchright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto(page_urls[0])
    await page.wait_for_load_state("load")

    col = _Collector()
    engine = ActionCaptureEngine(page, capture_screenshots=False)
    engine.add_callback(col)
    await engine.start()

    try:
        yield page, col, engine, page_urls
    finally:
        await engine.stop()
        await browser.close()
        await pw.stop()


async def test_capture_survives_navigation_and_restart(
    capture_harness: Any,
) -> None:
    """S3+S4+S5: capture works after nav, stop suppresses, restart is single."""
    page, col, engine, (_, page2_url) = capture_harness

    # S1 baseline on first page
    await page.click("#b")
    await asyncio.sleep(0.4)
    assert len(col.steps) == 1, f"baseline click not captured: {col.steps}"

    # S3: navigate to a fresh page, click must be captured again
    await page.goto(page2_url)
    await page.wait_for_load_state("load")
    n = len(col.steps)
    await page.click("#b")
    await asyncio.sleep(0.4)
    assert len(col.steps) == n + 1, "click after navigation was not captured"

    # S4: stop after navigation must suppress subsequent clicks
    await engine.stop()
    n = len(col.steps)
    await page.click("#b")
    await asyncio.sleep(0.4)
    assert len(col.steps) == n, "capture leaked after stop following navigation"

    # S5: restart must record exactly one step, never a duplicate
    await engine.start()
    n = len(col.steps)
    await page.click("#b")
    await asyncio.sleep(0.5)
    new_steps = col.steps[n:]
    assert len(new_steps) == 1, f"restart double-recorded: {new_steps}"
