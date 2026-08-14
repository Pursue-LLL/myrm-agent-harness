"""Test MutationObserver change detection accuracy."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    """Fresh pool for integration tests."""
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=2)
    yield pool
    await pool.shutdown()


@pytest.fixture
async def browser_session(browser_pool: GlobalBrowserPool) -> BrowserSession:
    """BrowserSession with real pool."""
    session = BrowserSession(browser_pool, ContextType.AGENT)
    yield session
    await session.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_observer_detects_text_content_change(browser_session: BrowserSession) -> None:
    """Test that MutationObserver detects textContent changes."""
    await browser_session.new_tab("about:blank")

    tab_handle = browser_session._tab_controller._tabs["tab0"]
    await tab_handle.page.set_content("<!DOCTYPE html><html><body><button id='btn'>Old</button></body></html>")

    manager = browser_session._snapshot_manager
    page_snapshot = manager._frame_registry

    await page_snapshot.capture(force_full=True)

    frame_state = page_snapshot._frame_states.get(0)
    assert frame_state is not None
    assert frame_state._observer.is_installed

    tab_handle = browser_session._tab_controller._tabs["tab0"]
    await tab_handle.page.evaluate("document.getElementById('btn').textContent = 'New';")
    await tab_handle.page.wait_for_timeout(100)

    changes = await tab_handle.page.evaluate("() => window.__ariaObserver ? window.__ariaObserver.getChanges() : []")

    print(f"Changes detected: {changes}")
    assert len(changes) > 0, "MutationObserver should detect textContent change"
    assert any(c.get("type") in ("text_added", "text_removed", "text_changed") for c in changes)

    print(" MutationObserver detects textContent changes")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_observer_detects_element_added(browser_session: BrowserSession) -> None:
    """Test that MutationObserver detects added elements."""
    await browser_session.new_tab("about:blank")

    tab_handle = browser_session._tab_controller._tabs["tab0"]
    await tab_handle.page.set_content("<!DOCTYPE html><html><body><button>Original</button></body></html>")

    manager = browser_session._snapshot_manager
    page_snapshot = manager._frame_registry

    await page_snapshot.capture(force_full=True)

    tab_handle = browser_session._tab_controller._tabs["tab0"]
    await tab_handle.page.evaluate("""
        const btn = document.createElement('button');
        btn.textContent = 'New';
        document.body.appendChild(btn);
    """)
    await tab_handle.page.wait_for_timeout(100)

    changes = await tab_handle.page.evaluate("() => window.__ariaObserver ? window.__ariaObserver.getChanges() : []")

    print(f"Changes detected: {changes}")
    assert len(changes) > 0, "MutationObserver should detect added element"
    assert any(c.get("type") == "added" for c in changes)

    print(" MutationObserver detects added elements")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_observer_detects_element_removed(browser_session: BrowserSession) -> None:
    """Test that MutationObserver detects removed elements."""
    await browser_session.new_tab("about:blank")

    tab_handle = browser_session._tab_controller._tabs["tab0"]
    html = (
        "<!DOCTYPE html><html><body>"
        "<button id='btn1'>Button 1</button>"
        "<button id='btn2'>Button 2</button>"
        "</body></html>"
    )
    await tab_handle.page.set_content(html)

    manager = browser_session._snapshot_manager
    page_snapshot = manager._frame_registry

    await page_snapshot.capture(force_full=True)

    tab_handle = browser_session._tab_controller._tabs["tab0"]
    await tab_handle.page.evaluate("document.getElementById('btn2').remove();")
    await tab_handle.page.wait_for_timeout(100)

    changes = await tab_handle.page.evaluate("() => window.__ariaObserver ? window.__ariaObserver.getChanges() : []")

    print(f"Changes detected: {changes}")
    assert len(changes) > 0, "MutationObserver should detect removed element"
    assert any(c.get("type") == "removed" for c in changes)

    print(" MutationObserver detects removed elements")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_observer_recovers_after_body_replacement(browser_session: BrowserSession) -> None:
    """Test that MutationObserver recovers after document.body is replaced.

    ``set_content`` uses a ``document.write``-style flow: the window/document
    survive but a brand-new body node is created. An observer installed on the
    old body silently misses all mutations on the live body. ``ensure_active``
    must re-anchor the observer onto the new body so change detection continues.
    """
    await browser_session.new_tab("about:blank")

    tab_handle = browser_session._tab_controller._tabs["tab0"]
    await tab_handle.page.set_content(
        "<!DOCTYPE html><html><body><button id='btn'>Old</button></body></html>"
    )

    manager = browser_session._snapshot_manager
    page_snapshot = manager._frame_registry

    await page_snapshot.capture(force_full=True)

    frame_state = page_snapshot._frame_states.get(0)
    assert frame_state is not None
    assert frame_state._observer.is_installed

    # Replace document.body the same way set_content does
    await tab_handle.page.evaluate(
        "() => {"
        "  const html = '<button id=\\'btn\\'>New</button>';"
        "  document.open(); document.write(html); document.close();"
        "}"
    )
    await tab_handle.page.wait_for_timeout(100)

    # The next capture must detect the stale observer and re-anchor it onto the
    # live body, then rebuild the cached tree from the new document.
    await page_snapshot.capture(force_full=False)
    assert frame_state._observer.is_installed
    first_tree = frame_state._cached_aria_tree or ""
    assert "New" in first_tree, "Post-replacement capture should rebuild from the new body"

    # Mutation on the NEW body must now be detected through the normal
    # incremental capture path (observer re-anchored, changes flow again).
    await tab_handle.page.evaluate("document.getElementById('btn').textContent = 'Changed';")
    await tab_handle.page.wait_for_timeout(100)
    await page_snapshot.capture(force_full=False)
    snap_tree = frame_state._cached_aria_tree or ""
    assert "Changed" in snap_tree, "Post-replacement snapshot should reflect the new body"

    # Verify the observer keeps tracking subsequent mutations (not just the
    # one that triggered the re-anchor) via repeated incremental captures.
    await tab_handle.page.evaluate("document.getElementById('btn').textContent = 'Final';")
    await tab_handle.page.wait_for_timeout(100)
    await page_snapshot.capture(force_full=False)
    snap_tree = frame_state._cached_aria_tree or ""
    assert "Final" in snap_tree, "Observer should keep tracking mutations after re-anchor"

    print(" MutationObserver recovers after body replacement")
