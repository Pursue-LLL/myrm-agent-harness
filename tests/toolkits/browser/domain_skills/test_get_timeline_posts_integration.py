"""Integration tests for x-com get_timeline_posts via browser_manage run_site_tool.

Uses real BrowserSession + Chromium snapshot pipeline (no mocks on the execution path).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.tools import create_browser_tools

_TIMELINE_HTML = """
<html>
  <body>
    <article>First X-style timeline post with enough text for extraction</article>
    <article>Second X-style timeline post with enough text for extraction</article>
  </body>
</html>
"""


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=1)
    yield pool
    await pool.shutdown()


@pytest.fixture
async def browser_session(browser_pool: GlobalBrowserPool) -> BrowserSession:
    session = BrowserSession(browser_pool, ContextType.AGENT)
    yield session
    await session.close()


def _browser_manage_tool(session: BrowserSession):
    tools = create_browser_tools(session)
    return {tool.name: tool for tool in tools}["browser_manage_tool"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_site_tool_extracts_article_posts(browser_session: BrowserSession) -> None:
    await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller.get_active_page()
    await page.set_content(_TIMELINE_HTML)
    await asyncio.sleep(0.3)

    browser_manage = _browser_manage_tool(browser_session)
    result = await browser_manage.ainvoke(
        {
            "action": "run_site_tool",
            "value": 'x-com:get_timeline_posts:{"max_posts": 5}',
        }
    )

    assert not result.startswith("Error"), result
    posts = json.loads(result)
    assert len(posts) >= 2
    combined = " ".join(post.get("text", "") for post in posts)
    assert "First X-style timeline post" in combined
    assert "Second X-style timeline post" in combined


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_site_tool_respects_max_posts(browser_session: BrowserSession) -> None:
    await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller.get_active_page()
    await page.set_content(_TIMELINE_HTML)
    await asyncio.sleep(0.3)

    browser_manage = _browser_manage_tool(browser_session)
    result = await browser_manage.ainvoke(
        {
            "action": "run_site_tool",
            "value": 'x-com:get_timeline_posts:{"max_posts": 1}',
        }
    )

    posts = json.loads(result)
    assert len(posts) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_site_tools_includes_x_com_get_timeline_posts(
    browser_session: BrowserSession,
) -> None:
    await browser_session.new_tab("about:blank")
    browser_manage = _browser_manage_tool(browser_session)

    result = await browser_manage.ainvoke({"action": "list_site_tools"})

    assert "x-com" in result
    assert "get_timeline_posts" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_site_tool_unknown_skill_returns_error(browser_session: BrowserSession) -> None:
    await browser_session.new_tab("about:blank")
    browser_manage = _browser_manage_tool(browser_session)

    result = await browser_manage.ainvoke(
        {
            "action": "run_site_tool",
            "value": "nonexistent-skill:missing_tool",
        }
    )

    assert result.startswith("Error:")
    assert "not found" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_site_tool_empty_value_returns_error(browser_session: BrowserSession) -> None:
    await browser_session.new_tab("about:blank")
    browser_manage = _browser_manage_tool(browser_session)

    result = await browser_manage.ainvoke({"action": "run_site_tool", "value": ""})

    assert result.startswith("Error:")
    assert "skill_id:tool_name" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_site_tool_invalid_json_args_returns_error(
    browser_session: BrowserSession,
) -> None:
    await browser_session.new_tab("about:blank")
    browser_manage = _browser_manage_tool(browser_session)

    result = await browser_manage.ainvoke(
        {
            "action": "run_site_tool",
            "value": "x-com:get_timeline_posts:{not-json}",
        }
    )

    assert result.startswith("Error:")
    assert "invalid JSON args" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_site_tool_missing_tool_in_skill_returns_error(
    browser_session: BrowserSession,
) -> None:
    await browser_session.new_tab("about:blank")
    browser_manage = _browser_manage_tool(browser_session)

    result = await browser_manage.ainvoke(
        {
            "action": "run_site_tool",
            "value": "x-com:nonexistent_tool",
        }
    )

    assert result.startswith("Error:")
    assert "not found in 'x-com'" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_site_tool_fallback_extract_text_without_article_role(
    browser_session: BrowserSession,
) -> None:
    await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller.get_active_page()
    await page.set_content(
        "<html><body><div>Fallback paragraph one with plenty of readable text</div>"
        "<div>Fallback paragraph two with plenty of readable text</div></body></html>"
    )
    await asyncio.sleep(0.3)

    browser_manage = _browser_manage_tool(browser_session)
    result = await browser_manage.ainvoke(
        {
            "action": "run_site_tool",
            "value": 'x-com:get_timeline_posts:{"max_posts": 3}',
        }
    )

    assert not result.startswith("Error"), result
    posts = json.loads(result)
    assert len(posts) >= 1
    combined = " ".join(post.get("text", "") for post in posts)
    assert "Fallback paragraph" in combined


@pytest.mark.integration
@pytest.mark.asyncio
async def test_standard_browser_snapshot_path_without_run_site_tool(
    browser_session: BrowserSession,
) -> None:
    """Agent-standard path: snapshot article refs directly (no domain site tool)."""
    await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller.get_active_page()
    await page.set_content(_TIMELINE_HTML)
    await asyncio.sleep(0.3)

    tools = create_browser_tools(browser_session)
    tool_dict = {tool.name: tool for tool in tools}
    snapshot_tool = tool_dict["browser_snapshot_tool"]

    snapshot_result = await snapshot_tool.ainvoke({})
    assert "article" in snapshot_result.lower()

    refs = browser_session.get_all_refs()
    article_texts = [
        info.name for info in refs.values() if info.role == "article" and len((info.name or "").strip()) > 10
    ]
    assert len(article_texts) >= 2
    assert any("First X-style" in text for text in article_texts)
    assert any("Second X-style" in text for text in article_texts)
