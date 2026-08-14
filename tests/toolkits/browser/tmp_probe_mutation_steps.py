"""Stepwise probe: find which step in harness capture path breaks the observer."""

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
async def test_mutation_observer_install_only() -> None:
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
        # Directly install observer only (bypass full_update)
        frame_state = await registry._create_frame_state(0)
        await frame_state._observer.install()
        print(f"[install_only] installed={frame_state._observer.is_installed}", flush=True)
        changes = await _edit_and_get_changes(page)
        print(f"[install_only] changes={changes}", flush=True)
        print("[install_only] DONE", flush=True)
    finally:
        await session.close()
        await pool.shutdown()


@pytest.mark.integration
async def test_mutation_observer_full_update_only() -> None:
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
        frame_state = await registry._create_frame_state(0)
        # Run full update without installing observer first (it installs internally)
        snapshot = await frame_state.capture(force_full=True)
        print(f"[full_update] source={snapshot.source}", flush=True)
        changes = await _edit_and_get_changes(page)
        print(f"[full_update] changes={changes}", flush=True)
        print("[full_update] DONE", flush=True)
    finally:
        await session.close()
        await pool.shutdown()
