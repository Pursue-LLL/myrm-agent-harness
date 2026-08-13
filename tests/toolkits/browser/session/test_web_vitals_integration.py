"""Integration tests for Web Vitals collection — real Chromium against a local HTTP server.

Covers the full chain without mocks:
- WebVitalsCollector.collect(): the injected JS actually runs in a real page
  (page.evaluate is the key path — buffered PerformanceObserver snapshots,
  NavigationTiming TTFB/FCP, ResourceTiming slow-resource attribution).
- BrowserSession.get_web_vitals(): agent-facing chain (new_tab → wait_for_load
  → report text) as invoked by the browser_manage_tool ``web_vitals`` action.

Run with: pytest -m integration tests/toolkits/browser/session/test_web_vitals_integration.py
"""

from __future__ import annotations

import base64
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.session.web_vitals import WebVitalsCollector

_PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: sans-serif; margin: 0; padding: 24px; }
    .hero { font-size: 3rem; font-weight: bold; color: #1a1a1a; }
    p { font-size: 1.1rem; line-height: 1.6; max-width: 60ch; }
  </style>
</head>
<body>
  <div class="hero">Core Web Vitals Integration Test</div>
  <p>Real Chromium measures this page. The image below is served with a
     deliberate delay so it shows up in the slow-resource attribution.</p>
  <img src="/slow.png" width="800" height="400" alt="slow image">
</body>
</html>
"""

# Minimal 1x1 transparent PNG.
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class _PageHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/slow.png":
            time.sleep(0.4)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(_PNG_BYTES)))
            self.end_headers()
            self.wfile.write(_PNG_BYTES)
            return
        body = _PAGE_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def page_server() -> str:
    """Local HTTP server serving a measurable page; returns its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PageHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/"
    yield base_url
    server.shutdown()
    server.server_close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_collect_real_page_full_metrics(
    browser_context, page_server: str
) -> None:
    """Collector runs the injected JS in a real page and grades the readings."""
    page = await browser_context.new_page()
    try:
        await page.goto(page_server, wait_until="load")
        report = await WebVitalsCollector().collect(page, page_server)
    finally:
        await page.close()

    assert report.url == page_server
    # NavigationTiming is always present after a real navigation.
    assert report.ttfb_ms is not None and report.ttfb_ms >= 0
    assert report.fcp_ms is not None and report.fcp_ms > 0
    # The page paints visible text, so LCP must have been finalized.
    assert report.lcp_ms is not None and report.lcp_ms > 0
    # No interaction happened, so INP stays unmeasured (graceful degradation).
    assert report.inp_ms is None
    # The delayed image lands in the slow-resource attribution.
    assert any("slow.png" in str(res.get("name", "")) for res in report.slow_resources)
    # Ratings and suggestions are derived, and the text is renderable.
    assert isinstance(report.suggestions, list)
    text = report.to_text()
    assert "Web Vitals for" in text
    assert "LCP" in text and "TTFB" in text and "FCP" in text
    assert "not measurable yet" in text


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_session_get_web_vitals_real_chain(page_server: str) -> None:
    """Agent-facing chain: navigate a real BrowserSession and read the report."""
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=1)
    session = BrowserSession(
        pool, ContextType.AGENT, allow_private_networks=True
    )
    try:
        tab_id = await session.new_tab(page_server)
        assert tab_id.startswith("tab")
        await session.wait_for_load()
        text = await session.get_web_vitals()
    finally:
        await session.close()
        await pool.shutdown()

    assert "Web Vitals for" in text
    assert "TTFB" in text and "LCP" in text and "FCP" in text
    assert "slow.png" in text
    assert "Rating" in text or "good" in text or "poor" in text
