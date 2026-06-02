"""Integration test: RefNotFoundError propagation through tool layer."""

from __future__ import annotations

import contextlib

import pytest

from myrm_agent_harness.toolkits import create_browser_tools
from myrm_agent_harness.toolkits.browser import (
    BrowserSession,
    RefNotFoundError,
)
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    """Create browser pool."""
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=1)
    yield pool
    await pool.shutdown()


@pytest.fixture
async def browser_session(browser_pool: GlobalBrowserPool) -> BrowserSession:
    """Create browser session."""
    session = BrowserSession(browser_pool, ContextType.AGENT)
    yield session
    await session.close()


@pytest.mark.asyncio
async def test_error_propagates_through_langchain_tool(browser_session: BrowserSession) -> None:
    """Test RefNotFoundError propagates correctly through LangChain tool layer.

    Verifies that:
    1. LangChain tool receives the structured error
    2. Error attributes are preserved
    3. Error message is actionable for LLM agents
    """
    tools = create_browser_tools(browser_session)
    interact_tool = next(t for t in tools if t.name == "browser_interact_tool")

    html = """
    <button id="action">Click Me</button>
    <input type="text" placeholder="Search">
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{html}`")
    await browser_session.snapshot()

    with pytest.raises(RefNotFoundError) as exc_info:
        await interact_tool.ainvoke({"action": "click", "ref": "e999"})

    error = exc_info.value
    assert error.ref == "e999"
    assert error.total_refs >= 2
    assert len(error.context_refs) >= 1
    assert "browser_snapshot(diff=False)" in str(error)
    assert error.context["action"] == "click"
    assert "page_url" in error.context
    assert error.context["page_url"] == "about:blank"


@pytest.mark.asyncio
async def test_metrics_available_via_session_stats(browser_session: BrowserSession) -> None:
    """Test metrics are accessible through session.stats for monitoring."""
    html = """<button>Click Me</button>"""

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{html}`")
    await browser_session.snapshot()

    initial_total = browser_session.stats["ref_failures"]["total_failures"]

    for ref in ["e99", "e98", "e99"]:
        with contextlib.suppress(RefNotFoundError):
            await browser_session.interact("click", ref)

    final_stats = browser_session.stats["ref_failures"]
    assert final_stats["total_failures"] == initial_total + 3
    assert final_stats["top_failed_refs"][0] == ("e99", 2)
    assert final_stats["top_failed_refs"][1] == ("e98", 1)


@pytest.mark.asyncio
async def test_context_refs_provide_multi_role_diversity(browser_session: BrowserSession) -> None:
    """Test context refs include diverse roles to help LLM understand options."""
    html = """
    <h1>Page Title</h1>
    <button>Button 1</button>
    <button>Button 2</button>
    <input type="text" placeholder="Input 1">
    <input type="text" placeholder="Input 2">
    <a href="#">Link 1</a>
    <a href="#">Link 2</a>
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
    assert "button" in roles or "clickable" in roles
