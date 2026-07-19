"""Real-browser E2E for Browser Platform Excellence (Slim Epic) changes."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.toolkits.browser.domain_filter import DomainAllowlist
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.session.browser_session_navigation_mixin import (
    _NAVIGATE_INTERACTIVE_SUMMARY_MAX_LINES,
)
from myrm_agent_harness.toolkits.browser.snapshot.aria_test_utils import extract_ref_ids
from myrm_agent_harness.toolkits.browser.tools import create_browser_tools
from myrm_agent_harness.utils.errors import ToolError

pytestmark = pytest.mark.e2e

_FORM_HTML = """
<!DOCTYPE html>
<html><body>
  <h1>Epic E2E</h1>
  <button id="go">Go</button>
  <input id="q" type="text" placeholder="Query"/>
</body></html>
"""


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=2)
    yield pool
    await pool.shutdown()


@pytest.fixture
async def browser_session(browser_pool: GlobalBrowserPool) -> BrowserSession:
    session = BrowserSession(browser_pool, ContextType.AGENT)
    yield session
    await session.close()


async def _load_form_page(session: BrowserSession) -> None:
    await session.new_tab("about:blank")
    page = session._tab_controller.get_active_page()
    await page.set_content(_FORM_HTML)
    await asyncio.sleep(0.3)


@pytest.mark.asyncio
async def test_navigate_includes_compact_interactive_refs(browser_session: BrowserSession) -> None:
    """B2: navigate appends compact interactive ref preview (real browser snapshot)."""
    await _load_form_page(browser_session)
    base = "Navigated to about:blank (status=200, title=Epic E2E)"
    result = await browser_session._append_navigate_interactive_summary(base)

    assert "Interactive refs (compact" in result
    assert f"max {_NAVIGATE_INTERACTIVE_SUMMARY_MAX_LINES}" in result
    assert "e0:" in result or "[ref=e0]" in result


@pytest.mark.asyncio
async def test_interact_batch_steps_real_browser(browser_session: BrowserSession) -> None:
    """B1: steps[] batch interact on real page."""
    await _load_form_page(browser_session)
    tools = {t.name: t for t in create_browser_tools(browser_session)}
    snapshot = tools["browser_snapshot_tool"]
    interact = tools["browser_interact_tool"]

    snap_text = await snapshot.ainvoke({"scope": "interactive", "diff": False})
    btn_ref = extract_ref_ids(snap_text, role_filter="button")[0]
    input_ref = extract_ref_ids(snap_text, role_filter="textbox")[0]

    result = await interact.ainvoke({
        "steps": [
            {"action": "fill", "ref": input_ref, "text": "hello"},
            {"action": "click", "ref": btn_ref},
        ],
    })

    assert "Step 1" in result
    assert "Step 2" in result


@pytest.mark.asyncio
async def test_navigate_blocklist_denies_real_session(browser_session: BrowserSession) -> None:
    """D1: session-level blocklist rejects navigation before network."""
    browser_session._domain_blocklist = DomainAllowlist.from_strings(["evil.test"])
    await browser_session.new_tab("about:blank")

    with pytest.raises(ToolError) as exc_info:
        await browser_session.navigate("https://evil.test/page")

    assert exc_info.value.error_code == "BROWSER_URL_BLOCKLIST"
    assert "evil.test" in str(exc_info.value)


@pytest.mark.asyncio
async def test_manage_wait_for_user_removed_real_tools(browser_session: BrowserSession) -> None:
    """A1: wait_for_user removed from browser_manage."""
    await _load_form_page(browser_session)
    tools = {t.name: t for t in create_browser_tools(browser_session)}
    manage = tools["browser_manage_tool"]

    result = await manage.ainvoke({"action": "wait_for_user"})
    assert "Unknown action" in result
    assert "wait_for_user" in result
