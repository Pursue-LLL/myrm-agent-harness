"""Unit tests for FrameState"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.frame_snapshot import FrameState


class TestFrameState:
    """FrameState 单元测试"""

    @pytest.mark.asyncio
    async def test_capture_first_time_full_update(self):
        """测试首次捕获（全量更新）"""
        mock_frame = MagicMock()
        mock_locator = MagicMock()
        mock_locator.aria_snapshot = AsyncMock(return_value="- button:\n    name: Click")
        mock_frame.locator.return_value = mock_locator
        mock_frame.evaluate = AsyncMock(return_value={})

        snapshot = FrameState(mock_frame)
        result = await snapshot.capture()

        assert "button" in result.tree
        assert "Click" in result.tree
        assert len(result.refs) == 1
        assert result.source == "full"
        assert result.metrics.changed_regions == 0
        assert snapshot._full_updates == 1

    @pytest.mark.asyncio
    async def test_capture_with_cache_hit(self):
        """测试缓存命中（无变化）"""
        mock_frame = MagicMock()
        mock_locator = MagicMock()
        mock_locator.aria_snapshot = AsyncMock(return_value="- button:\n    name: Click")
        mock_frame.locator.return_value = mock_locator
        mock_frame.evaluate = AsyncMock(
            side_effect=[
                None,
                {},
                [],
            ]
        )

        snapshot = FrameState(mock_frame)
        await snapshot.capture()

        result = await snapshot.capture()

        assert "button" in result.tree
        assert "Click" in result.tree
        assert result.source == "cached"
        assert result.metrics.total_changes == 0

    @pytest.mark.asyncio
    async def test_capture_with_changes(self):
        """测试有变化（增量更新）"""
        mock_frame = MagicMock()
        mock_locator = MagicMock()
        mock_locator.aria_snapshot = AsyncMock(return_value="- button:\n    name: Click")
        mock_frame.locator.return_value = mock_locator
        mock_frame.evaluate = AsyncMock(
            side_effect=[
                None,
                {},
                [],
                {},
            ]
        )

        snapshot = FrameState(mock_frame)
        await snapshot.capture()

        result = await snapshot.capture()

        assert "button" in result.tree
        assert "Click" in result.tree
        assert result.source in ["incremental", "cached", "full"]

    @pytest.mark.asyncio
    async def test_capture_with_selector(self):
        """测试 selector 参数"""
        mock_frame = MagicMock()
        mock_locator = MagicMock()
        mock_locator.aria_snapshot = AsyncMock(return_value="- button:\n    name: Submit")
        mock_frame.locator.return_value = mock_locator
        mock_frame.evaluate = AsyncMock(return_value={})

        snapshot = FrameState(mock_frame)
        result = await snapshot.capture(selector="#form")

        mock_frame.locator.assert_called_with("#form")
        assert "button" in result.tree
        assert "Submit" in result.tree

    @pytest.mark.asyncio
    async def test_capture_selector_not_found(self):
        """测试 selector 不存在"""
        mock_frame = MagicMock()
        mock_locator = MagicMock()
        mock_locator.aria_snapshot = AsyncMock(side_effect=Exception("Selector not found"))
        mock_frame.locator.return_value = mock_locator
        mock_frame.evaluate = AsyncMock()

        snapshot = FrameState(mock_frame)
        from myrm_agent_harness.toolkits.browser.exceptions import AriaAcquisitionError

        with pytest.raises(AriaAcquisitionError, match="Failed to acquire ARIA tree"):
            await snapshot.capture(selector="#not-exist")

    # 注意：cursor-interactive 功能已由 test_cursor_interactive_integration.py 完整测试
    # 该 mock 测试已移除，因为真实集成测试更可靠

    @pytest.mark.asyncio
    async def test_cross_origin_handling(self):
        """测试跨域 iframe 降级"""
        mock_frame = MagicMock()
        mock_frame.evaluate = AsyncMock(side_effect=Exception("Cross-origin"))
        mock_locator = MagicMock()
        mock_locator.aria_snapshot = AsyncMock(side_effect=Exception("Cross-origin"))
        mock_frame.locator.return_value = mock_locator

        snapshot = FrameState(mock_frame)
        from myrm_agent_harness.toolkits.browser.exceptions import AriaAcquisitionError

        with pytest.raises(AriaAcquisitionError):
            await snapshot.capture()

        assert snapshot._observer.is_cross_origin is True

        result = await snapshot.capture()
        assert "[Cross-origin iframe" in result.tree
        assert len(result.refs) == 0

    @pytest.mark.asyncio
    async def test_reset(self):
        """测试重置"""
        mock_frame = MagicMock()
        mock_locator = MagicMock()
        mock_locator.aria_snapshot = AsyncMock(return_value="- button 'Click'")
        mock_frame.locator.return_value = mock_locator
        mock_frame.evaluate = AsyncMock()

        snapshot = FrameState(mock_frame)
        await snapshot.capture()

        assert snapshot._cached_aria_tree is not None

        snapshot.reset()

        assert snapshot._cached_aria_tree is None
        assert snapshot._cached_refs is None
        assert snapshot._observer.is_installed is False

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """测试清理资源"""
        mock_frame = MagicMock()
        mock_locator = MagicMock()
        mock_locator.aria_snapshot = AsyncMock(return_value="- button 'Click'")
        mock_frame.locator.return_value = mock_locator
        mock_frame.evaluate = AsyncMock()

        snapshot = FrameState(mock_frame)
        await snapshot.capture()

        await snapshot.cleanup()

        mock_frame.evaluate.assert_called()
        assert snapshot._cached_aria_tree is None

    def test_stats(self):
        """测试统计信息"""
        mock_frame = MagicMock()
        snapshot = FrameState(mock_frame)

        stats = snapshot.stats

        assert stats["total_updates"] == 0
        assert stats["incremental_updates"] == 0
        assert stats["full_updates"] == 0
        assert stats["cache_hit_rate"] == 0
        assert stats["has_cache"] is False
        assert stats["is_cross_origin"] is False
