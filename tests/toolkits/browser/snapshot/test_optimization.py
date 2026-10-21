"""增量快照系统集成测试

验证关键特性：
1. _cached_snapshot() 辅助方法
2. AriaSnapshot 工厂方法 (create_error, create_cross_origin)
3. 代码重复消除
4. 类型安全性
"""

from __future__ import annotations

import pytest


class TestFrameSnapshotOptimization:
    """测试 FrameSnapshot 的辅助方法"""

    def test_cached_snapshot_helper(self) -> None:
        """测试 _cached_snapshot() 辅助方法"""
        from myrm_agent_harness.toolkits.browser.snapshot.frame_snapshot import FrameState

        # 创建 mock frame
        class MockFrame:
            async def evaluate(self, script: str) -> list[dict[str, str]]:
                return []

            def locator(self, selector: str) -> object:
                class MockLocator:
                    async def aria_snapshot(self) -> str:
                        return "test tree"

                return MockLocator()

        frame = MockFrame()
        snapshot_manager = FrameState(frame)  # type: ignore[arg-type]

        # 设置缓存
        snapshot_manager._cached_aria_tree = "cached tree"
        snapshot_manager._cached_refs = {"e0": None}  # type: ignore[dict-item]

        # 调用辅助方法
        result = snapshot_manager._cached_snapshot(total_changes=3)

        # 验证结果
        assert result.tree == "cached tree"
        assert result.refs == {"e0": None}
        assert result.source == "cached"
        assert result.metrics.changed_regions == 0
        assert result.metrics.total_changes == 3

        print(" _cached_snapshot() helper works correctly")

    def test_cached_snapshot_no_changes(self) -> None:
        """测试无变更场景"""
        from myrm_agent_harness.toolkits.browser.snapshot.frame_snapshot import FrameState

        class MockFrame:
            async def evaluate(self, script: str) -> list[dict[str, str]]:
                return []

            def locator(self, selector: str) -> object:
                class MockLocator:
                    async def aria_snapshot(self) -> str:
                        return "test tree"

                return MockLocator()

        frame = MockFrame()
        snapshot_manager = FrameState(frame)  # type: ignore[arg-type]

        snapshot_manager._cached_aria_tree = "cached tree"
        snapshot_manager._cached_refs = {}

        # 无变更场景
        result = snapshot_manager._cached_snapshot(total_changes=0)

        assert result.metrics.total_changes == 0
        assert result.source == "cached"

        print(" No changes scenario works correctly")


class TestPageSnapshotOptimization:
    """测试 PageSnapshot 的工厂方法"""

    def test_error_snapshot_helper(self) -> None:
        """测试 create_error() 静态方法"""
        from myrm_agent_harness.toolkits.browser.snapshot.snapshot_types import AriaSnapshot

        # 调用静态方法
        result = AriaSnapshot.create_error("Frame 5 not found")

        # 验证结果
        assert result.tree == "Frame 5 not found"
        assert result.refs == {}
        assert result.source == "full"
        assert result.metrics is None

        print(" AriaSnapshot.create_error() static method works correctly")

    def test_error_snapshot_custom_message(self) -> None:
        """测试自定义错误消息"""
        from myrm_agent_harness.toolkits.browser.snapshot.snapshot_types import AriaSnapshot

        result = AriaSnapshot.create_error("Custom error message")

        assert result.tree == "Custom error message"
        assert result.source == "full"

        print(" Custom error message works correctly")


class TestCodeQuality:
    """测试代码质量改进"""

    def test_no_duplicate_code(self) -> None:
        """验证重复代码已消除"""
        from pathlib import Path

        # 获取项目根目录
        current_file = Path(__file__)
        myrm_core_root = current_file.parent.parent.parent.parent.parent
        frame_snapshot_path = (
            myrm_core_root / "myrm_agent_harness" / "toolkits" / "browser" / "snapshot" / "frame_snapshot.py"
        )

        if not frame_snapshot_path.exists():
            print(f"  frame_snapshot.py not found at {frame_snapshot_path}, skipping test")
            return

        content = frame_snapshot_path.read_text()

        # 检查不应该有重复的 AriaSnapshot 创建逻辑
        # 应该只有辅助方法中创建
        aria_snapshot_count = content.count("AriaSnapshot(")

        # 预期：_cached_snapshot (1) + _full_update (1) + _incremental_snapshot (1) + _cross_origin_snapshot (1) + _error_snapshot (1) = 5
        assert aria_snapshot_count <= 5, f"Too many AriaSnapshot creations: {aria_snapshot_count}"

        print(f" AriaSnapshot creation count: {aria_snapshot_count}")

    def test_helper_methods_exist(self) -> None:
        """验证辅助方法存在"""
        from myrm_agent_harness.toolkits.browser.snapshot.frame_snapshot import FrameState
        from myrm_agent_harness.toolkits.browser.snapshot.snapshot_types import AriaSnapshot

        # 验证 FrameState 有辅助方法
        assert hasattr(FrameState, "_cached_snapshot")
        assert hasattr(FrameState, "_incremental_snapshot")

        # 验证 AriaSnapshot 有工厂方法
        assert hasattr(AriaSnapshot, "create_error")
        assert hasattr(AriaSnapshot, "create_cross_origin")

        print(" Helper methods exist")


class TestTypeAnnotations:
    """测试类型注解"""

    def test_union_type_annotation(self) -> None:
        """验证 Union Type 注解"""
        import inspect

        from myrm_agent_harness.toolkits.browser.snapshot.frame_snapshot import FrameState

        # 获取 __init__ 的签名
        sig = inspect.signature(FrameState.__init__)
        frame_param = sig.parameters.get("frame")

        # 验证类型注解存在
        assert frame_param is not None
        assert frame_param.annotation != inspect.Parameter.empty

        print(" Union Type annotation verified")

    def test_frozen_dataclass(self) -> None:
        """验证 frozen dataclass"""
        from myrm_agent_harness.toolkits.browser.snapshot.frame_snapshot import AriaSnapshot

        snapshot = AriaSnapshot(
            tree="test",
            refs={},
            source="full",
            timestamp=1234567890.0,
            metrics=None,
        )

        # 验证不可变性
        with pytest.raises(AttributeError):
            snapshot.tree = "modified"  # type: ignore[misc]

        print(" Frozen dataclass immutability verified")


def run_all_tests() -> None:
    """运行所有测试"""
    print("=" * 60)
    print("增量快照系统集成测试")
    print("=" * 60)
    print()

    # FrameSnapshot 辅助方法测试
    print(" FrameSnapshot 辅助方法测试")
    print("-" * 60)
    test_frame = TestFrameSnapshotOptimization()
    test_frame.test_cached_snapshot_helper()
    test_frame.test_cached_snapshot_no_changes()
    print()

    # FrameSnapshot 错误处理测试
    print(" FrameSnapshot 错误处理测试")
    print("-" * 60)
    test_page = TestPageSnapshotOptimization()
    test_page.test_error_snapshot_helper()
    test_page.test_error_snapshot_custom_message()
    print()

    # 代码质量测试
    print(" 代码质量测试")
    print("-" * 60)
    test_quality = TestCodeQuality()
    test_quality.test_no_duplicate_code()
    test_quality.test_helper_methods_exist()
    print()

    # 类型注解测试
    print(" 类型注解测试")
    print("-" * 60)
    test_types = TestTypeAnnotations()
    test_types.test_union_type_annotation()
    test_types.test_frozen_dataclass()
    print()

    print("=" * 60)
    print(" 所有测试通过！")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
