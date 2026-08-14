"""Probe: exact binary search between _get_frame_snapshot vs direct FrameState.capture."""

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
async def test_mutation_observer_binary() -> None:
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

        # STEP 1: exact _get_frame_snapshot path
        print("[bin] step1: _get_frame_snapshot", flush=True)
        snap1 = await registry._get_frame_snapshot(frame_index=0, force_full=True)
        print(f"[bin] step1 source={snap1.source}", flush=True)
        print(f"[bin] step1 changes={await _edit_and_get(page)}", flush=True)

        # STEP 2: reinstall fresh on same state and call capture
        fs = registry._frame_states[0]
        await fs._observer.disconnect()
        fs._observer.reset()
        await fs._observer.install()
        print("[bin] step2: reinstall+direct capture(force_full=True)", flush=True)
        snap2 = await fs.capture(force_full=True)
        print(f"[bin] step2 source={snap2.source}", flush=True)
        print(f"[bin] step2 changes={await _edit_and_get(page)}", flush=True)

        # STEP 3: mimic _get_frame_snapshot's capture_kwargs exactly
        await fs._observer.disconnect()
        fs._observer.reset()
        await fs._observer.install()
        print("[bin] step3: reinstall+capture(**kwargs like registry)", flush=True)
        snap3 = await fs.capture(
            force_full=True,
            cursor_interactive=False,
            selector="",
            scope="interactive",
            compact=False,
            max_depth=None,
            max_tokens=0,
        )
        print(f"[bin] step3 source={snap3.source}", flush=True)
        print(f"[bin] step3 changes={await _edit_and_get(page)}", flush=True)

        print("[bin] DONE", flush=True)
    finally:
        await session.close()
        await pool.shutdown()
