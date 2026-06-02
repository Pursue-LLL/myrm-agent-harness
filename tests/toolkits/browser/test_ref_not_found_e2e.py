"""End-to-end test for RefNotFoundError through LangChain tools."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits import create_browser_tools
from myrm_agent_harness.toolkits.browser import (
    BrowserSession,
    RefNotFoundError,
)
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    """Create browser pool for E2E tests."""
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=1)
    yield pool
    await pool.shutdown()


@pytest.fixture
async def browser_session(browser_pool: GlobalBrowserPool) -> BrowserSession:
    """Create real browser session."""
    session = BrowserSession(browser_pool, ContextType.AGENT)
    yield session
    await session.close()


@pytest.mark.asyncio
async def test_ref_not_found_error_propagation(browser_session: BrowserSession) -> None:
    """Test RefNotFoundError propagates with structured context through tools."""
    tools = create_browser_tools(browser_session)
    interact_tool = next(t for t in tools if t.name == "browser_interact_tool")

    html = """
    <!DOCTYPE html>
    <html>
        <body>
            <button id="btn1">Click Me</button>
            <button id="btn2">Submit</button>
        </body>
    </html>
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{html}`")
    await browser_session.snapshot()

    with pytest.raises(RefNotFoundError) as exc_info:
        await interact_tool.ainvoke({"action": "click", "ref": "e99"})

    error = exc_info.value
    assert error.ref == "e99"
    assert error.total_refs >= 2
    assert len(error.context_refs) >= 1
    assert "browser_snapshot(diff=False)" in str(error)
    assert error.context["action"] == "click"
    assert "page_url" in error.context
    assert error.context["page_url"] == "about:blank"


@pytest.mark.asyncio
async def test_metrics_collection_real_session(browser_session: BrowserSession) -> None:
    """Test metrics are collected in real browser session."""
    html = """
    <button>Click Me</button>
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{html}`")
    await browser_session.snapshot()

    initial_stats = browser_session.stats
    assert initial_stats["ref_failures"]["total_failures"] == 0

    with pytest.raises(RefNotFoundError):
        await browser_session.interact("click", "e99")

    stats = browser_session.stats
    assert stats["ref_failures"]["total_failures"] == 1
    assert stats["ref_failures"]["top_failed_refs"][0][0] == "e99"


@pytest.mark.asyncio
async def test_ref_not_found_context_refs_real_page(browser_session: BrowserSession) -> None:
    """Test context refs provide useful information in real scenario."""
    html = """
    <h1>Test Page</h1>
    <button id="submit">Submit Form</button>
    <button id="cancel">Cancel</button>
    <input type="text" placeholder="Username">
    <input type="password" placeholder="Password">
    <a href="#">Forgot password?</a>
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{html}`")
    await browser_session.snapshot()

    with pytest.raises(RefNotFoundError) as exc_info:
        await browser_session.interact("click", "e999")

    error = exc_info.value
    assert len(error.context_refs) >= 3
    roles = {r["role"] for r in error.context_refs}
    assert len(roles) >= 2
    assert any("button" in r["role"] for r in error.context_refs)
