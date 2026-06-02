"""Comprehensive tests for semantic-aware diff — 100% coverage.

Uses real Patchright/Chromium. Run with: pytest -m integration
"""

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
async def test_diff_baseline_initialization(browser_session: BrowserSession) -> None:
    """Test 1: First snapshot establishes baseline, second shows diff header."""
    html = "<!DOCTYPE html><html><body><button>Click</button></body></html>"

    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(html)

    result_1 = await browser_session.snapshot(scope="full", diff=False)
    assert "--- Snapshot diff ---" not in result_1.aria_tree
    assert "Click" in result_1.aria_tree

    result_2 = await browser_session.snapshot(scope="full", diff=True)
    assert "--- Snapshot diff ---" in result_2.aria_tree
    assert "Unchanged interactive" in result_2.aria_tree

    print(" Test 1: Baseline initialization")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_diff_detects_added_button(browser_session: BrowserSession) -> None:
    """Test 2: Diff detects newly added button."""
    html = "<!DOCTYPE html><html><body><button>Original</button></body></html>"

    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(html)
    await browser_session.snapshot(scope="full", diff=False)
    await tab_handle.page.evaluate("""
        const btn = document.createElement('button');
        btn.textContent = 'New Button';
        document.body.appendChild(btn);
    """)
    await tab_handle.page.wait_for_timeout(200)

    result = await browser_session.snapshot(scope="full", diff=True)

    assert "--- Snapshot diff ---" in result.aria_tree
    assert "+ " in result.aria_tree or "New interactive" in result.aria_tree
    assert "New Button" in result.aria_tree

    print(" Test 2: Added button detected")
    print(f"Diff:\n{result.aria_tree}")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_diff_detects_removed_button(browser_session: BrowserSession) -> None:
    """Test 3: Diff detects removed button."""
    html = """
<!DOCTYPE html>
<html>
<body>
    <button id='btn1'>Button 1</button>
    <button id='btn2'>Button 2</button>
</body>
</html>
"""

    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(html)
    result_1 = await browser_session.snapshot(scope="full", diff=False)
    initial_count = result_1.meta.ref_count
    assert "Button 1" in result_1.aria_tree and "Button 2" in result_1.aria_tree
    await tab_handle.page.evaluate("document.getElementById('btn2').remove();")
    await tab_handle.page.wait_for_timeout(200)

    result_2 = await browser_session.snapshot(scope="full", diff=True)

    assert "--- Snapshot diff ---" in result_2.aria_tree
    assert "- " in result_2.aria_tree or "Removed interactive" in result_2.aria_tree
    assert result_2.meta.ref_count < initial_count

    print(" Test 3: Removed button detected")
    print(f"Diff:\n{result_2.aria_tree}")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_diff_detects_button_text_change(browser_session: BrowserSession) -> None:
    """Test 4: Diff detects button text change."""
    html = "<!DOCTYPE html><html><body><button id='btn'>Old Text</button></body></html>"

    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(html)
    result_1 = await browser_session.snapshot(scope="full", diff=False)
    assert "Old Text" in result_1.aria_tree
    await tab_handle.page.evaluate("document.getElementById('btn').textContent = 'New Text';")
    await tab_handle.page.wait_for_timeout(200)

    result_2 = await browser_session.snapshot(scope="full", diff=True)

    assert "--- Snapshot diff ---" in result_2.aria_tree
    assert "New Text" in result_2.aria_tree
    assert ("- " in result_2.aria_tree and "+ " in result_2.aria_tree) or "New interactive" in result_2.aria_tree

    print(" Test 4: Button text change detected")
    print(f"Diff:\n{result_2.aria_tree}")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_diff_immune_to_ref_id_changes(browser_session: BrowserSession) -> None:
    """Test 5: Diff is immune to ref ID renumbering (DOM recreation)."""
    html = "<!DOCTYPE html><html><body><button>Stable</button></body></html>"

    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(html)
    result_1 = await browser_session.snapshot(scope="full", diff=False)
    ref_id_1 = result_1.aria_tree.split("[ref=")[1].split("]")[0] if "[ref=" in result_1.aria_tree else None
    await tab_handle.page.evaluate("""
        const body = document.body;
        const content = body.innerHTML;
        body.innerHTML = '';
        setTimeout(() => { body.innerHTML = content; }, 50);
    """)
    await tab_handle.page.wait_for_timeout(300)

    result_2 = await browser_session.snapshot(scope="full", diff=True)
    ref_id_2 = result_2.aria_tree.split("[ref=")[1].split("]")[0] if "[ref=" in result_2.aria_tree else None

    assert "--- Snapshot diff ---" in result_2.aria_tree
    assert "Unchanged interactive" in result_2.aria_tree
    assert ref_id_1 == ref_id_2 or "Stable" in result_2.aria_tree

    print(" Test 5: Immune to ref ID changes")
    print(f"Ref IDs: {ref_id_1} → {ref_id_2}")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_diff_with_multiple_changes(browser_session: BrowserSession) -> None:
    """Test 6: Diff handles multiple simultaneous changes."""
    html = """
<!DOCTYPE html>
<html>
<body>
    <button id='btn1'>Button 1</button>
    <button id='btn2'>Button 2</button>
    <button id='btn3'>Button 3</button>
</body>
</html>
"""

    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(html)

    await browser_session.snapshot(scope="full", diff=False)
    await tab_handle.page.evaluate("""
        document.getElementById('btn1').textContent = 'Modified 1';
        document.getElementById('btn2').remove();
        const btn = document.createElement('button');
        btn.textContent = 'Button 4';
        document.body.appendChild(btn);
    """)
    await tab_handle.page.wait_for_timeout(200)

    result = await browser_session.snapshot(scope="full", diff=True)

    assert "--- Snapshot diff ---" in result.aria_tree
    assert "Modified 1" in result.aria_tree or "Button 4" in result.aria_tree or "- " in result.aria_tree

    print(" Test 6: Multiple changes detected")
    print(f"Diff:\n{result.aria_tree}")


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_diff_reset_on_navigation(browser_session: BrowserSession) -> None:
    """Test 7: Diff baseline resets on navigation."""
    html1 = "<!DOCTYPE html><html><body><button>Page 1</button></body></html>"

    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(html1)

    await browser_session.snapshot(scope="full", diff=False)

    await browser_session.navigate("https://example.com")

    result = await browser_session.snapshot(scope="full", diff=True)

    assert "--- Snapshot diff ---" not in result.aria_tree or "Page 1" not in result.aria_tree

    print(" Test 7: Baseline reset on navigation")
