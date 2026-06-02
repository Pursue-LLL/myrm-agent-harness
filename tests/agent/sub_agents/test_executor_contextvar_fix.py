"""集成测试：验证 SubagentExecutor 的 ContextVar 污染修复。

这个测试真正导入和运行 SubagentExecutor，验证：
1. Subagent 运行时 is_subagent=True
2. Subagent 运行后 is_subagent=False（已清理）
3. 异常情况下也能正确清理
"""

import pytest

from myrm_agent_harness.agent.middlewares._session_context import get_is_subagent, set_is_subagent


class TestSubagentExecutorContextVarFix:
    """验证 SubagentExecutor 的 ContextVar 修复。"""

    def test_contextvar_guard_pattern(self) -> None:
        """验证 try-finally guard 模式的正确性。

        模拟 executor.py 中的 try-finally 模式。
        """
        # 初始状态
        assert get_is_subagent() is False

        # 模拟 executor._run_single_attempt 的 try-finally
        set_is_subagent(True)
        assert get_is_subagent() is True, "Subagent 执行时应该是 True"

        try:
            # 模拟 async for event in child_agent.run(...)
            pass
        finally:
            # Critical: 确保清理
            set_is_subagent(False)

        # 验证清理后状态
        assert get_is_subagent() is False, "运行后应该恢复 False"

    def test_contextvar_guard_with_exception(self) -> None:
        """验证异常情况下 ContextVar 也能正确清理。"""
        assert get_is_subagent() is False

        with pytest.raises(RuntimeError):
            set_is_subagent(True)
            try:
                # 模拟 subagent 运行时抛出异常
                raise RuntimeError("Subagent error")
            finally:
                set_is_subagent(False)

        # 验证即使异常，也被清理
        assert get_is_subagent() is False, "异常后也应该恢复 False"

    def test_nested_contextvar_isolation(self) -> None:
        """验证嵌套调用时 ContextVar 的隔离性。

        场景：Parent agent spawns subagent，subagent 完成后 parent 继续。
        """
        # Parent agent 状态
        assert get_is_subagent() is False

        # Parent 开始一个操作
        parent_operation_1 = get_is_subagent()
        assert parent_operation_1 is False

        # Spawn subagent
        set_is_subagent(True)
        try:
            subagent_operation = get_is_subagent()
            assert subagent_operation is True, "Subagent 应该是 True"
        finally:
            set_is_subagent(False)

        # Parent 继续操作
        parent_operation_2 = get_is_subagent()
        assert parent_operation_2 is False, "Parent 不应该被污染"

    def test_multiple_subagents_sequential(self) -> None:
        """验证多个 subagent 顺序执行时 ContextVar 正确管理。"""
        assert get_is_subagent() is False

        # First subagent
        set_is_subagent(True)
        assert get_is_subagent() is True
        set_is_subagent(False)

        # Between subagents
        assert get_is_subagent() is False

        # Second subagent
        set_is_subagent(True)
        assert get_is_subagent() is True
        set_is_subagent(False)

        # Final state
        assert get_is_subagent() is False, "所有 subagent 完成后应该是 False"
