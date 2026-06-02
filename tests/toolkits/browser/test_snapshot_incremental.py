"""增量快照系统单元测试

测试 snapshot 模块中的核心组件：
1. AriaSnapshot 不可变性与工厂方法
2. FrameState 缓存机制与统计跟踪
3. FrameRegistry 主框架捕获与重置
"""

from dataclasses import FrozenInstanceError

import pytest

from myrm_agent_harness.toolkits.browser.snapshot import (
    AriaSnapshot,
    FrameRegistry,
    FrameState,
)


class TestAriaSnapshot:
    """测试 AriaSnapshot 不可变性"""

    def test_immutability(self):
        """测试 frozen dataclass 不可变性"""
        snapshot = AriaSnapshot(
            tree="test tree",
            refs={},
            source="full",
            timestamp=1234567890.0,
            metrics=None,
        )

        with pytest.raises((FrozenInstanceError, AttributeError)):
            snapshot.timestamp = 0.0

    def test_creation(self):
        """测试快照创建"""
        from myrm_agent_harness.toolkits.browser.snapshot import SnapshotMetrics

        snapshot = AriaSnapshot(
            tree="- button 'Test'",
            refs={"e0": "test"},
            source="full",
            timestamp=1234567890.0,
            metrics=SnapshotMetrics(
                ref_count=1,
                estimated_tokens=10,
                changed_regions=1,
                total_changes=10,
            ),
        )

        assert snapshot.tree == "- button 'Test'"
        assert len(snapshot.refs) == 1
        assert snapshot.source == "full"
        assert snapshot.metrics.changed_regions == 1
        assert snapshot.metrics.total_changes == 10


class TestFrameStateHelpers:
    """测试 FrameState 辅助方法"""

    class MockFrame:
        """模拟 Frame 对象"""

        async def evaluate(self, script: str):
            return []

        def locator(self, selector: str):
            class MockLocator:
                async def aria_snapshot(self):
                    return "- button 'Test'"

            return MockLocator()

    def test_cached_snapshot(self):
        """测试 _cached_snapshot 辅助方法"""
        frame = self.MockFrame()
        manager = FrameState(frame)

        manager._cached_aria_tree = "cached tree"
        manager._cached_refs = {"e0": "test"}

        snapshot = manager._cached_snapshot(total_changes=3)

        assert snapshot.tree == "cached tree"
        assert snapshot.refs == {"e0": "test"}
        assert snapshot.source == "cached"
        assert snapshot.metrics.total_changes == 3
        assert snapshot.metrics.changed_regions == 0

    def test_cached_snapshot_empty_cache(self):
        """测试空缓存场景"""
        frame = self.MockFrame()
        manager = FrameState(frame)

        snapshot = manager._cached_snapshot(total_changes=0)

        assert snapshot.tree == ""
        assert snapshot.refs == {}
        assert snapshot.source == "cached"

    def test_cross_origin_snapshot(self):
        """测试 AriaSnapshot.create_cross_origin() 快照"""
        snapshot = AriaSnapshot.create_cross_origin()

        assert snapshot.tree == "[Cross-origin iframe - content not accessible]"
        assert snapshot.refs == {}
        assert snapshot.source == "full"
        assert snapshot.metrics is None

    def test_error_snapshot(self):
        """测试 AriaSnapshot.create_error() 静态方法"""
        snapshot = AriaSnapshot.create_error("Frame 5 not found")

        assert snapshot.tree == "Frame 5 not found"
        assert snapshot.refs == {}
        assert snapshot.source == "full"
        assert snapshot.metrics is None

    def test_error_snapshot_different_messages(self):
        """测试不同错误消息"""
        snapshot1 = AriaSnapshot.create_error("Frame not found")
        snapshot2 = AriaSnapshot.create_error("Cross-origin access denied")

        assert snapshot1.tree == "Frame not found"
        assert snapshot2.tree == "Cross-origin access denied"


class TestFrameStateCaching:
    """测试 FrameState 缓存机制"""

    class MockFrame:
        """模拟 Frame 对象"""

        def __init__(self):
            self.eval_count = 0

        async def evaluate(self, script: str):
            self.eval_count += 1
            if "ariaObserver" in script and "init" in script:
                return None
            return []

        def locator(self, selector: str):
            class MockLocator:
                async def aria_snapshot(self):
                    return "- button:\n    name: Test Button"

            return MockLocator()

    @pytest.mark.asyncio
    async def test_first_capture_full_update(self):
        """测试首次捕获执行全量更新"""
        frame = self.MockFrame()
        manager = FrameState(frame)

        snapshot = await manager.capture(force_full=True)

        assert snapshot.source == "full"
        assert len(snapshot.tree) > 0
        assert manager._cached_aria_tree is not None

    @pytest.mark.asyncio
    async def test_second_capture_uses_cache(self):
        """测试第二次捕获使用缓存"""
        frame = self.MockFrame()
        manager = FrameState(frame)

        snapshot1 = await manager.capture(force_full=True)
        snapshot2 = await manager.capture(force_full=False)

        assert snapshot2.source == "cached"
        assert snapshot2.metrics.total_changes == 0
        assert snapshot2.tree == snapshot1.tree

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """测试统计信息跟踪"""
        frame = self.MockFrame()
        manager = FrameState(frame)

        await manager.capture(force_full=True)
        await manager.capture(force_full=False)

        stats = manager.stats

        assert stats["total_updates"] == 2
        assert stats["full_updates"] == 1
        assert stats["has_cache"] is True

    @pytest.mark.asyncio
    async def test_reset_clears_cache(self):
        """测试 reset 清除缓存"""
        frame = self.MockFrame()
        manager = FrameState(frame)

        await manager.capture(force_full=True)
        assert manager._cached_aria_tree is not None

        manager.reset()

        assert manager._cached_aria_tree is None
        assert manager._cached_refs is None


class TestFrameRegistryIntegration:
    """测试 FrameRegistry 集成"""

    class MockPage:
        """模拟 Page 对象"""

        def __init__(self):
            self.frames = [self]

        async def evaluate(self, script: str):
            if "ariaObserver" in script and "init" in script:
                return None
            return []

        def locator(self, selector: str):
            class MockLocator:
                async def aria_snapshot(self):
                    return "- button:\n    name: Main Button"

            return MockLocator()

    @pytest.mark.asyncio
    async def test_capture_main_frame(self):
        """测试捕获主框架"""
        page = self.MockPage()
        manager = FrameRegistry(page)

        aria_tree, refs, source = await manager.capture(include_iframes=False, force_full=True)

        assert len(aria_tree) > 0
        assert isinstance(refs, dict)
        assert isinstance(source, str)

    @pytest.mark.asyncio
    async def test_reset_clears_all_frames(self):
        """测试 reset 清除所有 Frame"""
        page = self.MockPage()
        manager = FrameRegistry(page)

        await manager.capture(include_iframes=False, force_full=True)
        assert len(manager._frame_states) > 0

        manager.reset()

        assert len(manager._frame_states) == 0

    @pytest.mark.asyncio
    async def test_stats(self):
        """测试统计信息"""
        page = self.MockPage()
        manager = FrameRegistry(page)

        await manager.capture(include_iframes=False, force_full=True)

        stats = manager.stats

        assert "total_frames" in stats
        assert "frame_stats" in stats
        assert stats["total_frames"] >= 1
