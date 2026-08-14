"""Probe: track observe calls and observer state across install -> full_update -> edit."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow, pytest.mark.asyncio]

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession


@pytest.mark.integration
async def test_mutation_observer_track_phases() -> None:
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=2)
    session = BrowserSession(pool, ContextType.AGENT)
    try:
        await session.new_tab("about:blank")
        tab = session._tab_controller._tabs["tab0"]
        page = tab.page
        await page.set_content("<!DOCTYPE html><html><body><button id='btn'>Old</button></body></html>")

        await page.evaluate(
            "() => {"
            "  window.__observeLog = [];"
            "  const orig = MutationObserver.prototype.observe;"
            "  MutationObserver.prototype.observe = function(target, opts) {"
            "    window.__observeLog.push({ t: Date.now(), tag: target ? target.tagName : null, conn: target ? target.isConnected : null });"
            "    return orig.call(this, target, opts);"
            "  };"
            "  return 'hooked';"
            "}"
        )

        manager = session._snapshot_manager
        registry = manager._frame_registry

        # PHASE 1: install only
        fs = await registry._create_frame_state(0)
        await fs._observer.install()
        s1 = await page.evaluate(
            "() => ({ log: window.__observeLog, obsCount: window.__ariaObserver ? window.__ariaObserver.observers.length : -1 })"
        )
        print(f"[phase] AFTER_INSTALL log={s1['log']} obsCount={s1['obsCount']}", flush=True)
        await page.evaluate("window.__observeLog = [];")

        # Edit and get changes (before full_update)
        await page.evaluate("document.getElementById('btn').textContent = 'P1';")
        await page.wait_for_timeout(200)
        c1 = await page.evaluate("() => window.__ariaObserver ? window.__ariaObserver.getChanges() : []")
        print(f"[phase] CHANGES_AFTER_INSTALL_EDIT={c1}", flush=True)

        # PHASE 2: full_update
        await fs.capture(force_full=True)
        s2 = await page.evaluate(
            "() => ({ log: window.__observeLog, obsCount: window.__ariaObserver ? window.__ariaObserver.observers.length : -1, bodyHtml: document.body.innerHTML })"
        )
        print(f"[phase] AFTER_FULLUPDATE log={s2['log']} obsCount={s2['obsCount']} bodyHtml={s2['bodyHtml']}", flush=True)

        # Edit again and get changes
        await page.evaluate("document.getElementById('btn').textContent = 'P2';")
        await page.wait_for_timeout(200)
        c2 = await page.evaluate("() => window.__ariaObserver ? window.__ariaObserver.getChanges() : []")
        print(f"[phase] CHANGES_AFTER_FULLUPDATE_EDIT={c2}", flush=True)
        print("[phase] DONE", flush=True)
    finally:
        await session.close()
        await pool.shutdown()
