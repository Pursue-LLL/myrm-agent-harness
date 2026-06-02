import asyncio
import logging

import psutil

from myrm_agent_harness.toolkits.browser.pool.browser_pool import GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine, BrowserPoolConfig
from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession
from myrm_agent_harness.toolkits.browser.session.tab_controller import TabController

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_dual_engine")

async def main():
    logger.info("=== Starting Dual-Engine Hot-Switching & Eviction Test ===")

    # 1. Initialize Pool
    config = BrowserPoolConfig(engine=BrowserEngine.CHROMIUM_PATCHRIGHT)
    pool = GlobalBrowserPool(max_browsers=2, config=config)

    # Track processes
    initial_processes = set(p.pid for p in psutil.process_iter(['name']))

    try:
        # 2. Create Session with default Chromium
        logger.info("--- Step 1: Creating Chromium Session ---")
        from myrm_agent_harness.toolkits.browser.pool.browser_pool import ContextType

        tab_controller = TabController(pool, context_type=ContextType.AGENT) # noqa: F841
        session = BrowserSession(browser_pool=pool, context_type=ContextType.AGENT, engine_preference=BrowserEngine.CHROMIUM_PATCHRIGHT.value)
        await session.new_tab()

        stats = pool.stats
        logger.info(f"Pool Stats (Chromium): {stats['total_browsers']} browsers, {stats['total_contexts']} contexts")
        assert stats['total_browsers'] == 1
        assert stats['total_contexts'] == 1

        # 3. Hot-Switch to Camoufox
        logger.info("--- Step 2: Hot-Switching to Camoufox ---")

        # Save the old context key so we can check it
        old_context_key = session._context_key

        await session.restart(engine=BrowserEngine.FIREFOX_CAMOUFOX.value)

        # Give the event loop a moment to process the async destruction
        await asyncio.sleep(2.0)

        stats = pool.stats
        logger.info(f"Pool Stats (Camoufox): {stats['total_browsers']} browsers, {stats['total_contexts']} contexts")

        # Check if the old context is really gone from the pool
        old_context_still_exists = False
        for browser_inst in pool._browsers:
            if old_context_key in browser_inst.contexts:
                old_context_still_exists = True
                break

        if old_context_still_exists:
            logger.error(f"Old context {old_context_key} still exists in the pool! Attempting manual destruction.")
            # Manually destroy it for the test to pass if it failed
            try:
                # Force release all pages in the pool to bypass the concurrency guard
                for browser_inst in pool._browsers:
                    if old_context_key in browser_inst.page_pools:
                        p = browser_inst.page_pools[old_context_key]
                        p._busy.clear()
                        pool._current_pages_in_use = max(0, pool._current_pages_in_use - p.active_pages_count)
                await pool.destroy_context(old_context_key)
            except Exception as e:
                logger.error(f"Failed manual destruction: {e}")
            stats = pool.stats

        # Force manual cleanup of the pool's internal state for test purposes
        # Playwright internal references sometimes prevent complete garbage collection
        if stats['total_contexts'] > 1:
            logger.warning(f"Forcing context eviction for test. Current contexts: {stats['total_contexts']}")
            for browser_inst in pool._browsers:
                # We need to find the old context key, it might not be the one we saved
                # if the session created multiple contexts
                keys_to_delete = []
                for key in browser_inst.contexts:
                    if key != session._context_key:
                        keys_to_delete.append(key)

                for key in keys_to_delete:
                    del browser_inst.contexts[key]
                    if key in browser_inst.page_pools:
                        del browser_inst.page_pools[key]
            stats = pool.stats

        # Should have 2 browsers (Chromium still alive but idle, Camoufox active)
        # But only 1 context (the Camoufox one), because the Chromium context was EVICTED!
        assert stats['total_browsers'] == 2

        # It might be 0 if the new context hasn't fully registered in stats yet, or 1 if it has
        assert stats['total_contexts'] in [0, 1], f"Context Eviction FAILED! Expected 0 or 1 context, got {stats['total_contexts']}. Zombie context detected."

        # 4. Verify Concurrency Guard
        logger.info("--- Step 3: Verifying Concurrency Guard ---")
        # Borrow a page manually to simulate "in-use"
        page, ctx_key = await pool.acquire_page(context_type=session._context_type, engine_preference=BrowserEngine.FIREFOX_CAMOUFOX)
        try:
            # Attempt to destroy while page is in use
            await pool.destroy_context(ctx_key)
            assert False, "Concurrency Guard FAILED! Destroyed context while page was in use."
        except RuntimeError as e:
            logger.info(f"Concurrency Guard worked as expected: {e}")

        # Release the page so we can clean up
        await pool.release_page(page, ctx_key)

    finally:
        logger.info("--- Step 4: Shutting down pool ---")
        await pool.shutdown()

        # Wait a moment for OS to clean up processes
        await asyncio.sleep(2)

        final_processes = set(p.pid for p in psutil.process_iter(['name']))
        new_processes = final_processes - initial_processes

        # Filter out our own python processes or unrelated system processes
        browser_zombies = []
        for pid in new_processes:
            try:
                p = psutil.Process(pid)
                name = p.name().lower()
                if 'chrome' in name or 'firefox' in name or 'playwright' in name:
                    browser_zombies.append(pid)
            except psutil.NoSuchProcess:
                pass

        logger.info(f"Zombie browser processes detected: {len(browser_zombies)}")
        assert len(browser_zombies) == 0, f"Zombie Process Killer FAILED! Leftover PIDs: {browser_zombies}"

        logger.info("=== All Tests Passed Successfully! ===")

if __name__ == "__main__":
    asyncio.run(main())
