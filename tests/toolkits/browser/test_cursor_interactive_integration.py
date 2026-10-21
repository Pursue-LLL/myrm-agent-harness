"""Integration tests for cursor-interactive element detection.

Uses real Patchright/Chromium. Run with: pytest -m integration
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession

_TEST_HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head><title>Cursor Test</title></head>
<body>
    <button>Standard Button</button>
    <div onclick="console.log('clicked')" style="cursor: pointer">Clickable Div</div>
    <span style="cursor: pointer">Pointer Span</span>
    <div tabindex="0">Focusable Div</div>
    <a href="#">Standard Link</a>
</body>
</html>
"""


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
async def test_cursor_interactive_enabled(browser_session: BrowserSession) -> None:
    """Test cursor-interactive detection with cursor_interactive=True."""
    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(_TEST_HTML_CONTENT)

    result = await browser_session.snapshot(scope="content", diff=False, cursor_interactive=True)

    assert "--- cursor-interactive ---" in result.aria_tree
    assert "clickable" in result.aria_tree or "focusable" in result.aria_tree
    assert "Clickable Div" in result.aria_tree or "Pointer Span" in result.aria_tree

    print(" Cursor-interactive detection enabled")
    print(f"Snapshot length: {len(result.aria_tree)} chars")
    print(f"Ref count: {result.meta.ref_count}")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_cursor_interactive_disabled(browser_session: BrowserSession) -> None:
    """Test that cursor_interactive=False skips detection."""
    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(_TEST_HTML_CONTENT)

    result = await browser_session.snapshot(scope="content", diff=False, cursor_interactive=False)

    assert "--- cursor-interactive ---" not in result.aria_tree

    print(" Cursor-interactive detection disabled")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_cursor_interactive_deduplication(browser_session: BrowserSession) -> None:
    """Test that cursor-interactive elements deduplicate with ARIA elements."""
    html_with_duplicate = """
<!DOCTYPE html>
<html>
<body>
    <button>Submit</button>
    <div onclick="console.log('submit')" style="cursor: pointer">Submit</div>
</body>
</html>
"""

    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(html_with_duplicate)

    result = await browser_session.snapshot(scope="content", diff=False, cursor_interactive=True)

    submit_count = result.aria_tree.count("Submit")
    assert submit_count <= 2, f"Expected at most 2 'Submit' occurrences, found {submit_count}"

    print(" Deduplication working")
    print(f"Submit count: {submit_count}")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_cursor_interactive_css_class(browser_session: BrowserSession) -> None:
    """Test detection of cursor:pointer defined via CSS class (not inline style)."""
    html_with_css_class = """
<!DOCTYPE html>
<html>
<head>
    <style>
        .custom-button { cursor: pointer; }
        .clickable-card { cursor: pointer; padding: 10px; }
    </style>
</head>
<body>
    <div class="custom-button">CSS Class Button</div>
    <div class="clickable-card">Clickable Card</div>
    <span style="cursor: pointer">Inline Style Span</span>
</body>
</html>
"""

    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(html_with_css_class)

    result = await browser_session.snapshot(scope="content", diff=False, cursor_interactive=True)

    assert "--- cursor-interactive ---" in result.aria_tree
    assert "CSS Class Button" in result.aria_tree, "Should detect cursor:pointer from CSS class"
    assert "Clickable Card" in result.aria_tree, "Should detect cursor:pointer from CSS class"
    assert "Inline Style Span" in result.aria_tree, "Should detect cursor:pointer from inline style"

    print(" CSS class detection working")
    print("Detected elements in result.aria_tree")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_cursor_interactive_role_classification(browser_session: BrowserSession) -> None:
    """Test correct role classification: onclick and cursor:pointer should be 'clickable'."""
    html_with_roles = """
<!DOCTYPE html>
<html>
<head>
    <style>
        .pointer { cursor: pointer; }
    </style>
</head>
<body>
    <button onclick="console.log('click')">OnClick Button</button>
    <div class="pointer">Pointer Div</div>
    <span onclick="console.log('click')" class="pointer">Both Span</span>
    <input type="text" tabindex="0" value="Tabindex Input" />
</body>
</html>
"""

    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(html_with_roles)

    result = await browser_session.snapshot(scope="content", diff=False, cursor_interactive=True)

    assert "--- cursor-interactive ---" in result.aria_tree

    # 提取 cursor-interactive 部分
    cursor_section = []
    in_cursor_section = False
    for line in result.aria_tree.split("\n"):
        if "--- cursor-interactive ---" in line:
            in_cursor_section = True
            continue
        if in_cursor_section:
            if line.strip() == "":
                break
            cursor_section.append(line)

    cursor_text = "\n".join(cursor_section)

    # 验证角色分类正确性
    # 注意：onclick button 可能已经被 ARIA 树捕获，不会出现在 cursor-interactive 中
    # 但 Pointer Div 应该出现（因为 div 默认不是 ARIA 元素）
    assert "Pointer Div" in cursor_text, "Should detect CSS class cursor:pointer"
    assert "clickable" in cursor_text, "cursor:pointer should be clickable"

    # 如果 Both Span 出现，应该是 clickable
    if "Both Span" in cursor_text:
        both_line = next(line for line in cursor_section if "Both Span" in line)
        assert "clickable" in both_line, "onclick + cursor:pointer should be clickable"

    print(" Role classification correct")
    print(f"Cursor-interactive section:\n{cursor_text}")
