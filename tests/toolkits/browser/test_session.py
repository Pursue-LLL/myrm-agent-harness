"""Integration tests for BrowserSession"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from myrm_agent_harness.toolkits.browser import BrowserSession
from myrm_agent_harness.toolkits.browser.backends import FileVaultBackend
from myrm_agent_harness.toolkits.browser.backends.file_backend import load_or_create_key
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session_vault import SessionVault


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    """创建测试用的 GlobalBrowserPool"""
    pool = GlobalBrowserPool(max_browsers=2)
    await pool.warmup(browsers=1, pages_per_context=2)
    yield pool
    await pool.shutdown()


@pytest.fixture
def session_vault(tmp_path: Path) -> SessionVault:
    """Real SessionVault with temporary storage for tests."""
    vault_dir = tmp_path / "session_vault"
    key_path = tmp_path / "vault.key"

    backend = FileVaultBackend(vault_dir)
    encryption_key = load_or_create_key(key_path)
    return SessionVault(backend, encryption_key)


@pytest.fixture
async def session(browser_pool: GlobalBrowserPool, session_vault: SessionVault) -> BrowserSession:
    """创建测试用的 BrowserSession with SessionVault"""
    session = BrowserSession(browser_pool, ContextType.AGENT, session_vault=session_vault)
    await session.new_tab()
    yield session
    await session.close()


@pytest.mark.asyncio
async def test_create_and_close_tab(session: BrowserSession) -> None:
    """测试创建和关闭 Tab"""
    tab_id = await session.new_tab()
    assert tab_id.startswith("tab")

    tabs = session.list_tabs()
    assert len(tabs) == 2
    assert tab_id in tabs

    await session.close_tab(tab_id)
    tabs = session.list_tabs()
    assert len(tabs) == 1


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.asyncio
async def test_navigate(session: BrowserSession) -> None:
    """测试页面导航"""
    result = await session.navigate("https://example.com")
    assert "example.com" in result
    assert "status=200" in result


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.asyncio
async def test_snapshot(session: BrowserSession) -> None:
    """测试快照生成"""
    await session.navigate("https://example.com")

    aria_tree, metadata = await session.snapshot()
    assert "example" in aria_tree.lower()
    assert metadata["ref_count"] > 0
    assert metadata["estimated_tokens"] > 0


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.asyncio
async def test_snapshot_diff(session: BrowserSession) -> None:
    """测试快照 diff"""
    await session.navigate("https://example.com")

    aria_tree1, _ = await session.snapshot(diff=True)
    assert "--- Snapshot diff ---" not in aria_tree1

    aria_tree2, _ = await session.snapshot(diff=True)
    assert "--- Snapshot diff ---" in aria_tree2 or "unchanged" in aria_tree2.lower()


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.asyncio
async def test_extract_text(session: BrowserSession) -> None:
    """测试文本提取"""
    await session.navigate("https://example.com")

    text = await session.extract_text()
    assert len(text) > 0
    assert "example" in text.lower()


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.asyncio
async def test_extract_screenshot(session: BrowserSession) -> None:
    """测试截图提取"""
    await session.navigate("https://example.com")

    screenshot = await session.extract_screenshot()
    assert len(screenshot) > 100


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.asyncio
async def test_switch_tab(session: BrowserSession) -> None:
    """测试 Tab 切换"""
    tab1 = session.get_active_tab_id()
    await session.navigate("https://example.com")

    tab2 = await session.new_tab()
    await session.navigate("https://example.org")

    await session.switch_tab(tab1)
    assert session.get_active_tab_id() == tab1
    text1 = await session.extract_text()
    assert len(text1) > 0

    await session.switch_tab(tab2)
    assert session.get_active_tab_id() == tab2
    text2 = await session.extract_text()
    print(f"\nURL: {session._tab_controller.get_active_page().url}")
    print(f"TEXT2: {text2!r}")
    assert len(text2) > 0


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.asyncio
async def test_evaluate(session: BrowserSession) -> None:
    """测试 JS 执行"""
    await session.navigate("https://example.com")
    result = await session.evaluate("document.title")
    assert "example" in result.lower()


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.asyncio
async def test_go_back_forward(session: BrowserSession) -> None:
    """测试前进后退"""
    await session.navigate("https://example.com")
    await session.navigate("https://example.org")
    result = await session.go_back()
    assert "back" in result.lower()
    result = await session.go_forward()
    assert "forward" in result.lower()


@pytest.mark.asyncio
async def test_resize(session: BrowserSession) -> None:
    """测试视口调整"""
    result = await session.resize(1280, 720)
    assert "1280" in result
    assert "720" in result


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.asyncio
async def test_wait_for_load(session: BrowserSession) -> None:
    """测试等待加载"""
    await session.navigate("https://example.com")
    result = await session.wait_for_load()
    assert "load" in result.lower() or "completed" in result.lower()


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.asyncio
async def test_save_pdf(session: BrowserSession) -> None:
    """测试 PDF 导出"""
    await session.navigate("https://example.com")
    result = await session.save_pdf()
    assert "PDF" in result
    assert "Saved" in result


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.asyncio
async def test_session_persistence(session: BrowserSession) -> None:
    """测试会话持久化"""
    await session.navigate("https://example.com")
    save_result = await session.save_session("example.com")
    assert "Saved" in save_result

    list_result = await session.list_sessions()
    assert "example.com" in list_result

    restore_result = await session.restore_session("example.com")
    assert "Restored" in restore_result

    delete_result = await session.delete_session("example.com")
    assert "Deleted" in delete_result


def test_console_network_log(session: BrowserSession) -> None:
    """测试控制台和网络日志"""
    assert "console" in session.get_console_log().lower()
    assert "network" in session.get_network_log().lower()
