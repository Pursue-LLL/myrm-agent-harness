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
async def test_snapshot_manager_diff_output_integration() -> None:
    """测试 SnapshotManager 全流程集成：diff=True 时的 baseline 维护、Fast Path 与指标暴露"""
    mock_page = MagicMock()
    # 构建具有一定体积的树结构以验证 Token 节省度量
    tree_1 = "\n".join([f'  e{i}: [button] "Action item {i} in current view with detailed description"' for i in range(20)])
    refs_1 = {
        f"e{i}": RefInfo(role="button", name=f"Action item {i}", nth=None, bbox=None, position=None)
        for i in range(20)
    }

    with patch("myrm_agent_harness.toolkits.browser.snapshot.FrameRegistry") as mock_page_snapshot_cls:
        mock_snapshot = mock_page_snapshot_cls.return_value
        mock_snapshot.capture = AsyncMock(return_value=(tree_1, refs_1, False))

        manager = SnapshotManager(mock_page)

        # 首次捕获：建立 baseline，非增量
        res1 = await manager.get_snapshot(diff=True)
        assert res1.is_incremental is False
        assert res1.diff_output is None
        assert res1.is_identical is False

        # 第二次捕获（内容未变）：触发 Identical Fast Path
        res2 = await manager.get_snapshot(diff=True)
        assert res2.is_incremental is True
        assert res2.diff_output is not None
        assert res2.is_identical is True
        assert res2.tokens_saved > 0
        assert "--- Snapshot diff ---" in res2.aria_tree
        assert "No DOM changes detected" in res2.aria_tree

        # 第三次捕获（动态新增按钮）：产生 semantic diff
        tree_2 = tree_1 + '\n  e99: [button] "Dynamic Confirm Button"'
        refs_2 = {
            **refs_1,
            "e99": RefInfo(role="button", name="Dynamic Confirm Button", nth=None, bbox=None, position=None),
        }
        mock_snapshot.capture = AsyncMock(return_value=(tree_2, refs_2, False))

        res3 = await manager.get_snapshot(diff=True)
        assert res3.is_incremental is True
        assert res3.diff_output is not None
        assert res3.is_identical is False
        assert res3.additions > 0
        assert "Dynamic Confirm Button" in res3.aria_tree
        assert res3.is_fallback_full is False

        # 重置 baseline 测试
        manager.reset_diff_baseline()
        res4 = await manager.get_snapshot(diff=True)
        assert res4.is_incremental is False
        assert res4.diff_output is None


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
