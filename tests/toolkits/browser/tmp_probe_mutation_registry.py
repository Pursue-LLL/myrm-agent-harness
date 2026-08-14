"""Probe: isolate what FrameRegistry.capture does differently that breaks observer."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow, pytest.mark.asyncio]

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession


async def _edit_and_get_changes(page) -> list:
    await page.evaluate("document.getElementById('btn').textContent = 'New';")
    await page.wait_for_timeout(200)
    return await page.evaluate("() => window.__ariaObserver ? window.__ariaObserver.getChanges() : []")


@pytest.mark.integration
async def test_mutation_observer_registry_path() -> None:
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=2)
    session = BrowserSession(pool, ContextType.AGENT)
    try:
        await session.new_tab("about:blank")
        tab = session._tab_controller._tabs["tab0"]
        page = tab.page
        await page.set_content("<!DOCTYPE html><html><body><button id='btn'>Old</button></body></html>")

        manager = session._snapshot_manager
        registry = manager._frame_registry
        print(f"[reg] page.frames={len(page.frames)}", flush=True)

        # Path A: registry.capture (fails in prior probes)
        await registry.capture(force_full=True)
        print(f"[reg] after registry.capture frame_states={list(registry._frame_states.keys())}", flush=True)
        changes = await _edit_and_get_changes(page)
        print(f"[reg] changes_after_registry_capture={changes}", flush=True)

        # Now force-reset and retry with a direct install on the SAME frame state
        fs = registry._frame_states.get(0)
        if fs:
            print(f"[reg] fs.observer.installed={fs._observer.is_installed}", flush=True)
            await fs._observer.disconnect()
            fs._observer.reset()
            await fs._observer.install()
            changes2 = await _edit_and_get_changes(page)
            print(f"[reg] changes_after_reinstall_same_state={changes2}", flush=True)
        print("[reg] DONE", flush=True)
    finally:
        await session.close()
        await pool.shutdown()


@pytest.mark.integration
async def test_mutation_observer_pure_registry() -> None:
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=2)
    session = BrowserSession(pool, ContextType.AGENT)
    try:
        await session.new_tab("about:blank")
        tab = session._tab_controller._tabs["tab0"]
        page = tab.page
        await page.set_content("<!DOCTYPE html><html><body><button id='btn'>Old</button></body></html>")

        manager = session._snapshot_manager
        registry = manager._frame_registry
        # replicate registry.capture manually without iframe handling
        await registry._get_frame_snapshot(frame_index=0, force_full=True)
        print(f"[pure] after _get_frame_snapshot frame_states={list(registry._frame_states.keys())}", flush=True)
        changes = await _edit_and_get_changes(page)
        print(f"[pure] changes={changes}", flush=True)

        # Manual check: body identity inside observer vs page
        ident = await page.evaluate(
            "() => { const o = window.__ariaObserver; "
            "let obsBody = null; "
            "if (o && o.observers[0]) { "
            "  obsBody = o.observers[0]._observeTarget ? 'yes' : 'no'; "
            "} "
            "return { hasObserver: !!o, obsCount: o ? o.observers.length : -1 }; }"
        )
        print(f"[pure] ident={ident}", flush=True)
        print("[pure] DONE", flush=True)
    finally:
        await session.close()
        await pool.shutdown()
