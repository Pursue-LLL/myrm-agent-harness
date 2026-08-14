"""E2E tests — real-browser secret redaction on page content.

#170 BrowserOutputSecretRedaction: page-displayed credentials must never reach
the LLM context. Every browser tool result passes through ``mark_untrusted``
(``redact_sensitive_text`` then ``wrap_untrusted``) in ``tools/common.py``.

These tests run against a REAL browser (patchright) with a locally-injected
page that embeds credentials in plain sight, exercising every output-bearing
tool: snapshot / extract / manage (evaluate + console_log) / inspect /
navigate / execute_script.

The navigate test targets a real external URL (OAuth callback semantics) and
skips itself when the network is unavailable.

Run with: ./myrm test -m e2e tests/toolkits/browser/test_browser_e2e_secret_redaction.py
"""

from __future__ import annotations

import asyncio
import time
import urllib.request

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.tools import create_browser_tools

# fmt: off
SECRETS_PAGE = """<!DOCTYPE html>
<html><body>
  <h1>Dashboard</h1>
  <div id="secret">TOKEN=sk-proj-abcdefghijklmnop1234567890</div>
  <p id="cfg">app.api.key=mysecretvalue12345678</p>
  <code id="cmd">deploy --api-key=sk-abcdefghijklmnop1234 --env prod</code>
  <span id="pat">ghp_abcdefghijklmnop</span>
</body></html>"""
# fmt: on

# Plaintext secrets that must never survive a browser tool result.
_PLAINTEXT_SECRETS = (
    "sk-proj-abcdefghijklmnop1234567890",
    "mysecretvalue12345678",
    "sk-abcdefghijklmnop1234",
    "ghp_abcdefghijklmnop",
)
# Masked tails that prove redaction ran (kept readable, not collapsed to ***).
_MASKED_FRAGMENTS = (
    "sk-pro",
    "mysecr",
    "sk-abc",
    "ghp_ab",
)

# Values ≥18 chars keep first 6 + last 4 (e.g. oauthsecretcode12345 ->
# oauths...2345); shorter values collapse to ***. Used by the navigate test.
_OAUTH_CODE = "oauthsecretcode12345"


def _external_network_available() -> bool:
    """Probe the host the navigate test relies on; skip when unreachable."""
    try:
        urllib.request.urlopen("https://example.com", timeout=5).close()
        return True
    except Exception:
        return False


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    """Real browser pool for E2E tests."""
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=2)
    yield pool
    await pool.shutdown()


@pytest.fixture
async def browser_session(browser_pool: GlobalBrowserPool) -> BrowserSession:
    """BrowserSession with an injected secrets page."""
    session = BrowserSession(browser_pool, ContextType.AGENT)
    await session.new_tab("about:blank")
    page = session._tab_controller.get_active_page()
    await page.set_content(SECRETS_PAGE)
    await asyncio.sleep(0.5)
    yield session
    await session.close()


def _assert_secrets_redacted(result: str) -> None:
    for secret in _PLAINTEXT_SECRETS:
        assert secret not in result, f"leaked plaintext secret: {secret}"
    assert any(frag in result for frag in _MASKED_FRAGMENTS), (
        "no masked fragment survived — redaction may not have run on output"
    )


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_snapshot_redacts_page_secrets(
    browser_session: BrowserSession,
) -> None:
    """browser_snapshot output must redact page-displayed credentials."""
    tools = create_browser_tools(browser_session)
    tool_dict = {tool.name: tool for tool in tools}
    result = await tool_dict["browser_snapshot_tool"].ainvoke({"scope": "content"})
    _assert_secrets_redacted(result)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_extract_redacts_page_secrets(
    browser_session: BrowserSession,
) -> None:
    """browser_extract (text) output must redact page-displayed credentials."""
    tools = create_browser_tools(browser_session)
    tool_dict = {tool.name: tool for tool in tools}
    result = await tool_dict["browser_extract_tool"].ainvoke({"mode": "text"})
    _assert_secrets_redacted(result)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_manage_evaluate_redacts_page_secrets(
    browser_session: BrowserSession,
) -> None:
    """browser_manage evaluate returning page text must redact credentials."""
    tools = create_browser_tools(browser_session)
    tool_dict = {tool.name: tool for tool in tools}
    result = await tool_dict["browser_manage_tool"].ainvoke(
        {"action": "evaluate", "value": "document.getElementById('secret').innerText"}
    )
    _assert_secrets_redacted(result)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_inspect_redacts_page_secrets(
    browser_session: BrowserSession,
) -> None:
    """browser_inspect structural output must not leak page-displayed credentials.

    inspect returns structure metadata (regions/ref counts), not page text,
    so the assertion is plaintext absence rather than masked-fragment survival.
    """
    tools = create_browser_tools(browser_session)
    tool_dict = {tool.name: tool for tool in tools}
    result = await tool_dict["browser_inspect_tool"].ainvoke({})
    for secret in _PLAINTEXT_SECRETS:
        assert secret not in result, f"leaked plaintext secret: {secret}"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_navigate_redacts_oauth_code_query(
    browser_session: BrowserSession,
) -> None:
    """browser_navigate final-URL output must redact OAuth code query params.

    OAuth callback URLs (``?code=...``) are a normal auth flow — neither the
    URL exfiltration gate nor the SSRF shield blocks them, so redaction is the
    last defense before the final URL reaches the LLM context.
    """
    if not _external_network_available():
        pytest.skip("external network unavailable — cannot navigate to example.com")
    tools = create_browser_tools(browser_session)
    tool_dict = {tool.name: tool for tool in tools}
    result = await tool_dict["browser_navigate_tool"].ainvoke(
        {"url": f"https://example.com/?code={_OAUTH_CODE}&state=xyz"}
    )
    assert _OAUTH_CODE not in result, "OAuth code leaked in navigate output"
    assert "code=" in result, "query key must survive (only value is masked)"
    assert "oauths...2345" in result, "masked code tail must survive"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_manage_console_log_redacts_page_secrets(
    browser_session: BrowserSession,
) -> None:
    """browser_manage console_log must redact credentials logged by page JS."""
    page = browser_session._tab_controller.get_active_page()
    await page.set_content(
        "<!DOCTYPE html><html><body><script>"
        'console.log("loaded key sk-proj-abcdefghijklmnop1234567890")'
        "</script></body></html>"
    )
    console = await _wait_for_console_marker(browser_session)
    assert console, "console capture never received the secret log line"
    tools = create_browser_tools(browser_session)
    tool_dict = {tool.name: tool for tool in tools}
    result = await tool_dict["browser_manage_tool"].ainvoke({"action": "console_log", "value": ""})
    assert "sk-proj-abcdefghijklmnop1234567890" not in result


async def _wait_for_console_marker(browser_session: BrowserSession) -> str:
    """Poll console capture until the secret log line arrives (no fixed sleep)."""
    deadline = time.monotonic() + 5.0
    last = ""
    while time.monotonic() < deadline:
        last = browser_session.get_console_log()
        if "sk-proj-abcdefghijklmnop1234567890" in last:
            return last
        await asyncio.sleep(0.2)
    return last


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_execute_script_redacts_page_secrets(
    browser_session: BrowserSession,
) -> None:
    """browser_execute_script printed page text must redact credentials."""
    page = browser_session._tab_controller.get_active_page()
    await page.set_content('<html><body><div id="sec">TOKEN=sk-proj-abcdefghijklmnop1234567890</div></body></html>')
    await asyncio.sleep(0.5)
    tools = create_browser_tools(browser_session)
    tool_dict = {tool.name: tool for tool in tools}
    script = "text = await session.extract_text()\nprint(text)"
    result = await tool_dict["browser_execute_script_tool"].ainvoke({"script": script})
    assert "sk-proj-abcdefghijklmnop1234567890" not in result
    assert "sk-pro" in result
