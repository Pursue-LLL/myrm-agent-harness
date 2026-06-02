"""Comprehensive tests for SnapshotManager"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.session.snapshot_manager import SnapshotManager
from myrm_agent_harness.toolkits.browser.snapshot import RefInfo


@pytest.mark.asyncio
async def test_snapshot_with_optimization_tip() -> None:
    """测试快照生成时添加优化提示（覆盖line 149）"""
    mock_page = MagicMock()

    # 创建大页面数据（触发suggestion）
    large_aria_tree = "button e1: Submit\n" + "\n".join([f"button e{i}: Item {i}" for i in range(2, 252)])
    refs = {
        f"e{i}": RefInfo(role="button", name=f"Item {i}", nth=None, bbox=None, position=None) for i in range(1, 252)
    }

    with patch("myrm_agent_harness.toolkits.browser.snapshot.FrameRegistry") as mock_page_snapshot_cls:
        mock_snapshot = mock_page_snapshot_cls.return_value
        mock_snapshot.capture = AsyncMock(return_value=(large_aria_tree, refs, False))

        manager = SnapshotManager(mock_page)
        result = await manager.get_snapshot(scope="full", compact=False)

        # 应包含优化提示（251个refs会触发建议）
        assert " Optimization tip:" in result.tree
        assert "scope='interactive'" in result.tree or "compact=True" in result.tree
        assert result.meta.ref_count == len(refs)


@pytest.mark.asyncio
async def test_snapshot_no_optimization_tip() -> None:
    """测试小页面无优化提示"""
    mock_page = MagicMock()

    small_aria_tree = "button e1: Submit\nlink e2: Home"
    refs = {"e1": RefInfo(role="button", name="Submit", nth=None, bbox=None, position=None)}

    with patch("myrm_agent_harness.toolkits.browser.snapshot.FrameRegistry") as mock_page_snapshot_cls:
        mock_snapshot = mock_page_snapshot_cls.return_value
        mock_snapshot.capture = AsyncMock(return_value=(small_aria_tree, refs, False))

        manager = SnapshotManager(mock_page)
        result = await manager.get_snapshot()

        # 不应包含优化提示
        assert " Optimization tip:" not in result.tree
