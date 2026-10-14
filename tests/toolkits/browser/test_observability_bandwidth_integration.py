"""Real-Chromium proof that the context observer counts the bytes of a finished request.

`Request.response()` is a coroutine in the async driver; reading `.headers` off the un-awaited object
raised inside the handler, so every request was recorded with zero bytes. Run with:
`pytest -m integration tests/toolkits/browser/test_observability_bandwidth_integration.py`.
"""

from __future__ import annotations

import asyncio

import pytest
from patchright.async_api import async_playwright

from myrm_agent_harness.toolkits.browser.observability import BrowserObservability, RecordingConfig
from tests.toolkits.browser._browser_available import chromium_available
from tests.toolkits.browser._redirect_servers import page, serve

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_PAYLOAD_BYTES = 5000


async def test_a_finished_request_is_recorded_with_its_response_size() -> None:
    observability = BrowserObservability(RecordingConfig())
    with serve({"/": page("x" * _PAYLOAD_BYTES)}) as site:
        async with async_playwright() as driver:
            browser = await driver.chromium.launch(headless=True)
            try:
                context = await browser.new_context()
                observability.attach_to_context(context)
                tab = await context.new_page()
                await tab.goto(site.url("/"))
                async with asyncio.timeout(5):
                    while observability.telemetry.total_bytes_transferred == 0:
                        await asyncio.sleep(0.05)
            finally:
                await browser.close()

    assert observability.telemetry.total_bytes_transferred >= _PAYLOAD_BYTES
    assert observability.telemetry.request_count == 1
