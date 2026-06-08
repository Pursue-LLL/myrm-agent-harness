"""End-to-end test for context_refs usage in real LLM scenarios.

This test verifies:
1. RefNotFoundError provides useful context_refs
2. context_refs contain sufficient information for LLM decision-making
3. Different scenarios (page update, navigation, element removal) are handled
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser import (
    BrowserSession,
    RefNotFoundError,
)
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool

pytestmark = pytest.mark.e2e


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
async def test_scenario_page_dynamic_update(browser_session: BrowserSession) -> None:
    """场景1: 页面动态更新导致 ref 失效

    模拟：
    1. 初始快照获得 refs
    2. 页面 DOM 重新渲染
    3. 旧 ref 失效
    4. context_refs 应该包含新的"提交"按钮
    """
    # 初始页面
    initial_html = """
    <!DOCTYPE html>
    <html>
        <body>
            <h1>Loading...</h1>
            <div id="loader">Please wait...</div>
        </body>
    </html>
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{initial_html}`")
    snapshot1 = await browser_session.snapshot()

    # 获取初始 ref（假设 loader 的 ref）
    # 在真实场景中，LLM 会记住这个 ref
    initial_refs = [line.split()[0] for line in snapshot1.aria_tree.split("\n") if line.strip().startswith("e")]

    # 页面动态更新（模拟加载完成）
    updated_html = """
    <!DOCTYPE html>
    <html>
        <body>
            <h1>Form Ready</h1>
            <input type="text" placeholder="Username" />
            <input type="password" placeholder="Password" />
            <button id="submit">Submit</button>
            <button id="cancel">Cancel</button>
        </body>
    </html>
    """

    await browser_session.evaluate(f"document.body.innerHTML = `{updated_html}`")
    await browser_session.snapshot()

    # LLM 尝试使用旧的 ref
    if initial_refs:
        old_ref = initial_refs[0]
        with pytest.raises(RefNotFoundError) as exc_info:
            await browser_session.interact("click", old_ref)

        error = exc_info.value
        # 验证 context_refs 包含有用信息
        assert len(error.context_refs) >= 2
        assert error.total_refs >= 4  # 2 inputs + 2 buttons

        # 验证包含"Submit"按钮
        submit_button = [r for r in error.context_refs if "submit" in r["name"].lower()]
        assert len(submit_button) >= 1, "context_refs should include Submit button"

        # 验证多样性（至少 2 种不同的 role）
        roles = {r["role"] for r in error.context_refs}
        assert len(roles) >= 2, "context_refs should have diverse roles"

        # 验证 page_url
        assert error.context["page_url"] == "about:blank"


@pytest.mark.asyncio
async def test_scenario_similar_buttons(browser_session: BrowserSession) -> None:
    """场景2: 多个相似按钮，验证 context_refs 的智能采样

    验证：
    1. 优先展示有 name 的 refs
    2. 按 role 分组
    3. 提供多样化的样本
    """
    html = """
    <!DOCTYPE html>
    <html>
        <body>
            <h1>Button Gallery</h1>
            <button id="btn1">Primary Action</button>
            <button id="btn2">Secondary Action</button>
            <button id="btn3">Tertiary Action</button>
            <button id="btn4"></button>
            <button id="btn5"></button>
            <input type="text" placeholder="Search" />
            <input type="email" placeholder="Email" />
            <a href="#home">Home</a>
            <a href="#about">About</a>
            <div onclick="doSomething()">Clickable Div</div>
        </body>
    </html>
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{html}`")
    await browser_session.snapshot()

    with pytest.raises(RefNotFoundError) as exc_info:
        await browser_session.interact("click", "e999")

    error = exc_info.value

    # 验证智能采样：优先有 name 的 refs
    named_refs = [r for r in error.context_refs if r["name"]]
    unnamed_refs = [r for r in error.context_refs if not r["name"]]

    # 有 name 的应该更多（智能采样优先选择）
    if named_refs:
        assert len(named_refs) >= len(unnamed_refs) or len(error.context_refs) <= 5

    # 验证多样性
    roles = {r["role"] for r in error.context_refs}
    assert len(roles) >= 2, f"Expected diverse roles, got: {roles}"

    # 验证至少包含一个有意义的按钮名称
    button_names = [r["name"] for r in error.context_refs if r["role"] == "button"]
    assert any(name for name in button_names), "Should include named buttons"


@pytest.mark.asyncio
async def test_scenario_form_submission_navigation(
    browser_session: BrowserSession,
) -> None:
    """场景3: 表单提交后页面跳转

    验证：
    1. 新页面的 context_refs 完全不同
    2. LLM 可以从 context_refs 判断页面已变化
    """
    # 表单页
    form_html = """
    <!DOCTYPE html>
    <html>
        <body>
            <h1>Login Form</h1>
            <input type="text" id="username" placeholder="Username" />
            <input type="password" id="password" placeholder="Password" />
            <button id="login">Login</button>
        </body>
    </html>
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{form_html}`")
    snapshot1 = await browser_session.snapshot()

    # 获取登录按钮的 ref
    login_refs = [
        line.split()[0]
        for line in snapshot1.aria_tree.split("\n")
        if "login" in line.lower() and line.strip().startswith("e")
    ]

    # 模拟提交后跳转到成功页
    success_html = """
    <!DOCTYPE html>
    <html>
        <body>
            <h1>Login Successful!</h1>
            <p>Welcome back, user!</p>
            <button id="dashboard">Go to Dashboard</button>
            <button id="logout">Logout</button>
        </body>
    </html>
    """

    await browser_session.evaluate(f"document.body.innerHTML = `{success_html}`")
    await browser_session.snapshot()

    # LLM 尝试再次点击"Login"按钮（但页面已变）
    if login_refs:
        old_login_ref = login_refs[0]
        with pytest.raises(RefNotFoundError) as exc_info:
            await browser_session.interact("click", old_login_ref)

        error = exc_info.value

        # 验证 context_refs 完全不同（没有"Login"，有"Dashboard"）
        context_names = [r["name"].lower() for r in error.context_refs]
        assert not any("login" in name for name in context_names if name)
        assert any("dashboard" in name or "logout" in name for name in context_names if name), (
            "Should show new page buttons"
        )


@pytest.mark.asyncio
async def test_context_refs_information_completeness(
    browser_session: BrowserSession,
) -> None:
    """验证 context_refs 信息的完整性

    检查：
    1. ref ID 格式正确
    2. role 有意义
    3. name 存在且准确
    """
    html = """
    <!DOCTYPE html>
    <html>
        <body>
            <button id="submit">Submit Form</button>
            <input type="text" placeholder="Enter text" />
            <a href="#link">Click here</a>
            <select>
                <option>Option 1</option>
            </select>
        </body>
    </html>
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{html}`")
    await browser_session.snapshot()

    with pytest.raises(RefNotFoundError) as exc_info:
        await browser_session.interact("click", "e999")

    error = exc_info.value

    # 验证每个 context_ref 的完整性
    for ctx_ref in error.context_refs:
        # 必须有 ref ID
        assert ctx_ref["ref"], "ref ID must not be empty"
        assert ctx_ref["ref"].startswith("e") or ctx_ref["ref"].startswith("f"), f"Invalid ref format: {ctx_ref['ref']}"

        # 必须有 role
        assert ctx_ref["role"], "role must not be empty"

        # name 可以为空，但应该是字符串
        assert isinstance(ctx_ref["name"], str), "name must be string"

    # 验证至少有一些有 name 的元素
    named_count = sum(1 for r in error.context_refs if r["name"])
    assert named_count >= 1, "Should have at least one named element"


@pytest.mark.asyncio
async def test_context_refs_max_total_limit(browser_session: BrowserSession) -> None:
    """验证 context_refs 不会过多（max_total=15）

    即使页面有很多元素，context_refs 也应该控制在合理数量
    """
    # 创建一个有大量元素的页面
    buttons_html = "\n".join([f'<button id="btn{i}">Button {i}</button>' for i in range(50)])
    html = f"""
    <!DOCTYPE html>
    <html>
        <body>
            <h1>Many Buttons</h1>
            {buttons_html}
        </body>
    </html>
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{html}`")
    await browser_session.snapshot()

    with pytest.raises(RefNotFoundError) as exc_info:
        await browser_session.interact("click", "e999")

    error = exc_info.value

    # 验证 context_refs 数量被限制
    assert len(error.context_refs) <= 15, "context_refs should not exceed max_total"
    assert len(error.context_refs) >= 5, "context_refs should provide useful samples"

    # 验证总数是准确的
    assert error.total_refs >= 50, "total_refs should reflect actual count"


@pytest.mark.asyncio
async def test_context_refs_empty_page(browser_session: BrowserSession) -> None:
    """边界情况: 空页面

    验证：
    1. 空页面不会崩溃
    2. context_refs 为空或很少
    """
    html = """
    <!DOCTYPE html>
    <html>
        <body>
            <h1>Empty Page</h1>
        </body>
    </html>
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{html}`")
    await browser_session.snapshot()

    with pytest.raises(RefNotFoundError) as exc_info:
        await browser_session.interact("click", "e999")

    error = exc_info.value

    # 空页面应该有很少或没有 refs
    assert error.total_refs <= 5
    assert len(error.context_refs) <= error.total_refs
