"""Probe: is it first-install timing, or permanent break? Check second _get_frame_snapshot call."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow, pytest.mark.asyncio]

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession


async def _edit_and_get(page) -> list:
    await page.evaluate("document.getElementById('btn').textContent = 'New';")
    await page.wait_for_timeout(200)
    return await page.evaluate("() => window.__ariaObserver ? window.__ariaObserver.getChanges() : []")


@pytest.mark.integration
async def test_mutation_observer_timing() -> None:
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

        # STEP A: first _get_frame_snapshot (expected fail)
        await registry._get_frame_snapshot(frame_index=0, force_full=True)
        print(f"[time] stepA changes={await _edit_and_get(page)}", flush=True)

        # STEP B: second _get_frame_snapshot WITHOUT reinstall (installed=True still)
        await registry._get_frame_snapshot(frame_index=0, force_full=True)
        print(f"[time] stepB changes={await _edit_and_get(page)}", flush=True)

        # STEP C: third, but now do a plain non-forced capture first (get_changes path)
        await registry._frame_states[0].capture(force_full=False)
        print(f"[time] stepC (after non-forced capture) changes={await _edit_and_get(page)}", flush=True)

        print("[time] DONE", flush=True)
    finally:
        await session.close()
        await pool.shutdown()
