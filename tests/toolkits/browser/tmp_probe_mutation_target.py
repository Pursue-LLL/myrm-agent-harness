"""Probe: hook MutationObserver.observe to capture what target harness installs on."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow, pytest.mark.asyncio]

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession


@pytest.mark.integration
async def test_mutation_observer_observe_target() -> None:
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=2)
    session = BrowserSession(pool, ContextType.AGENT)
    try:
        await session.new_tab("about:blank")
        tab = session._tab_controller._tabs["tab0"]
        page = tab.page
        await page.set_content("<!DOCTYPE html><html><body><button id='btn'>Old</button></body></html>")

        # Hook observe to record targets
        await page.evaluate(
            "() => {"
            "  window.__observeLog = [];"
            "  const orig = MutationObserver.prototype.observe;"
            "  MutationObserver.prototype.observe = function(target, opts) {"
            "    window.__observeLog.push({"
            "      isBody: target === document.body,"
            "      tag: target ? target.tagName : null,"
            "      nodeType: target ? target.nodeType : null,"
            "      inDocument: target ? target.isConnected : null,"
            "      bodyIsCurrent: target === document.body"
            "    });"
            "    return orig.call(this, target, opts);"
            "  };"
            "  return 'hooked';"
            "}"
        )

        manager = session._snapshot_manager
        registry = manager._frame_registry
        await registry._get_frame_snapshot(frame_index=0, force_full=True)

        log = await page.evaluate("() => window.__observeLog")
        print(f"[target] observe_log={log}", flush=True)
        print("[target] DONE", flush=True)
    finally:
        await session.close()
        await pool.shutdown()
