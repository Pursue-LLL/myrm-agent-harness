"""Tests for iframe penetration feature."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class _FakePage:
    """Minimal mock of a Patchright Page with iframe support."""

    def __init__(self, url: str = "about:blank", num_iframes: int = 0):
        self.url = url
        self._closed = False
        self._title = "Main Page"

        # 创建 iframe frames
        self.frames = [self]  # 主框架
        for i in range(num_iframes):
            iframe = _FakeFrame(f"iframe_{i + 1}")
            self.frames.append(iframe)

    def is_closed(self) -> bool:
        return self._closed

    async def goto(self, url: str, **kw: object) -> MagicMock:
        self.url = url
        resp = MagicMock()
        resp.status = 200
        return resp

    async def close(self) -> None:
        self._closed = True

    async def evaluate(self, script: str, *args: object) -> MagicMock:
        return MagicMock()

    def locator(self, selector: str) -> MagicMock:
        loc = MagicMock()
        loc.aria_snapshot = AsyncMock(
            return_value='- button "Main Button"\n- link "Main Link"'
        )
        loc.page = MagicMock()
        loc.page.evaluate = AsyncMock(return_value=[])
        return loc


class _FakeFrame:
    """Mock of an iframe Frame."""

    def __init__(self, name: str):
        self.name = name
        self.url = f"https://example.com/{name}"

    async def evaluate(self, script: str, *args: object) -> MagicMock:
        return MagicMock()

    def locator(self, selector: str) -> MagicMock:
        loc = MagicMock()
        # iframe 内容
        loc.aria_snapshot = AsyncMock(
            return_value=f'- button "Frame {self.name} Button"\n- textbox "Frame {self.name} Input"'
        )
        loc.page = MagicMock()
        loc.page.evaluate = AsyncMock(return_value=[])
        return loc


@pytest.fixture
def page_with_iframes():
    """创建包含 2 个 iframe 的页面"""
    return _FakePage(num_iframes=2)


@pytest.mark.asyncio
async def test_snapshot_with_iframes(page_with_iframes):
    """测试 iframe 穿透功能"""
    from myrm_agent_harness.toolkits.browser.session.snapshot_manager import (
        SnapshotManager,
    )

    manager = SnapshotManager(page_with_iframes)

    result = await manager.get_snapshot(include_iframes=True, diff=False)

    # 检查主框架内容
    assert "Main Button" in result.aria_tree
    assert "Main Link" in result.aria_tree

    # 检查 iframe 标记
    assert "--- iframe 1 ---" in result.aria_tree
    assert "--- iframe 2 ---" in result.aria_tree

    # 检查 iframe 内容
    assert "Frame iframe_1 Button" in result.aria_tree
    assert "Frame iframe_2 Input" in result.aria_tree

    # 检查 refs 前缀
    # 主框架: e0, e1
    # iframe 1: f1_e0, f1_e1
    # iframe 2: f2_e0, f2_e1
    assert len(result.refs) == 6
    assert any(ref_id.startswith("f1_") for ref_id in result.refs)
    assert any(ref_id.startswith("f2_") for ref_id in result.refs)


@pytest.mark.asyncio
async def test_snapshot_without_iframes(page_with_iframes):
    """测试禁用 iframe 穿透"""
    from myrm_agent_harness.toolkits.browser.session.snapshot_manager import (
        SnapshotManager,
    )

    manager = SnapshotManager(page_with_iframes)

    result = await manager.get_snapshot(include_iframes=False, diff=False)

    # 只有主框架内容
    assert "Main Button" in result.aria_tree
    assert "Main Link" in result.aria_tree

    # 没有 iframe 标记
    assert "--- iframe 1 ---" not in result.aria_tree
    assert "--- iframe 2 ---" not in result.aria_tree

    # 只有主框架 refs
    assert len(result.refs) == 2
    assert all(not ref_id.startswith("f") for ref_id in result.refs)


@pytest.mark.asyncio
async def test_snapshot_with_selector_skips_iframes(page_with_iframes):
    """测试 selector 设置时自动跳过 iframe"""
    from myrm_agent_harness.toolkits.browser.session.snapshot_manager import (
        SnapshotManager,
    )

    manager = SnapshotManager(page_with_iframes)

    # selector 设置时，即使 include_iframes=True 也会跳过
    result = await manager.get_snapshot(
        selector=".main-content", include_iframes=True, diff=False
    )

    # 没有 iframe 内容
    assert "--- iframe 1 ---" not in result.aria_tree


@pytest.mark.asyncio
async def test_iframe_ref_format():
    """测试 iframe ref ID 格式"""
    from myrm_agent_harness.toolkits.browser.session.snapshot_manager import (
        SnapshotManager,
    )

    page = _FakePage(num_iframes=3)
    manager = SnapshotManager(page)

    result = await manager.get_snapshot(include_iframes=True, diff=False)

    # 检查 ref ID 格式
    iframe_refs = [ref_id for ref_id in result.refs if ref_id.startswith("f")]

    # 应该有 f1_*, f2_*, f3_* 格式的 refs
    assert any(ref_id.startswith("f1_") for ref_id in iframe_refs)
    assert any(ref_id.startswith("f2_") for ref_id in iframe_refs)
    assert any(ref_id.startswith("f3_") for ref_id in iframe_refs)

    # 每个 iframe 应该有 2 个 refs（button + textbox/input/link）
    f1_refs = [r for r in iframe_refs if r.startswith("f1_")]
    assert len(f1_refs) == 2
