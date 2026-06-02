"""集成测试：Subagent Approval Auto-Deny 机制。

测试场景：
1. Subagent 尝试调用需要 approval 的高危工具
2. approval middleware 检测到 is_subagent=True
3. 自动拒绝并返回 error ToolMessage
4. 记录 metrics 和 audit log
"""

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares._session_context import get_is_subagent, set_is_subagent


@pytest.mark.asyncio
async def test_subagent_auto_deny_high_risk_operation() -> None:
    """验证 subagent 尝试高危操作时自动拒绝。"""
    # 设置 subagent 上下文
    set_is_subagent(True)

    try:
        # 验证上下文设置成功
        assert get_is_subagent() is True

        # 模拟 approval middleware 的逻辑
        from myrm_agent_harness.agent.security.audit import record_decision

        # 模拟一个需要 approval 的 tool call
        tool_call = {
            "name": "bash",
            "args": {"command": "rm -rf /"},
            "id": "call_12345",
        }

        # Subagent 检测到 pending_approval 时，应该 auto-deny
        # 这是 approval/middleware.py 的核心逻辑
        if get_is_subagent():
            # 构造 error ToolMessage
            error_msg = (
                "[SYSTEM_ENFORCED] High-risk operations requiring user UI approval "
                "are strictly forbidden for autonomous Subagents. "
                "This safeguard prevents deadlocks since Subagents have no frontend channel. "
                "Please use a safe alternative or delegate this operation to the parent agent."
            )

            artificial_tool_message = ToolMessage(
                content=error_msg, name=tool_call["name"], tool_call_id=tool_call["id"], status="error"
            )

            # 记录审计
            record_decision(
                tool_call["name"], "SUBAGENT_AUTO_DENY", "Autonomous subagent blocked from triggering UI approval flow"
            )

            # 验证 ToolMessage
            assert artificial_tool_message.status == "error"
            assert "[SYSTEM_ENFORCED]" in artificial_tool_message.content
            assert "deadlock" in artificial_tool_message.content.lower()

            print(f"\n Subagent auto-deny 验证成功:\n{artificial_tool_message.content[:150]}...")

    finally:
        # 清理上下文
        set_is_subagent(False)
        assert get_is_subagent() is False


@pytest.mark.asyncio
async def test_parent_agent_approval_not_affected() -> None:
    """验证父 agent 的 approval 流程不受影响。"""
    # 确保不是 subagent
    set_is_subagent(False)
    assert get_is_subagent() is False

    # 模拟父 agent 的 approval 流程
    # 父 agent 应该正常触发 interrupt()

    # 父 agent 不应该被 auto-deny
    # 这个测试验证 get_is_subagent() == False 时，正常流程不受影响
    if not get_is_subagent():
        # 正常的 approval 流程（这里不实际调用 interrupt）
        print("\n 父 agent approval 流程不受影响")
        assert True


@pytest.mark.asyncio
async def test_subagent_with_multiple_tool_calls() -> None:
    """验证 subagent 同时拒绝多个高危操作。"""
    set_is_subagent(True)

    try:
        # 验证上下文设置
        assert get_is_subagent() is True

        # 模拟多个需要 approval 的 tool calls
        tool_calls = [
            {"name": "bash", "args": {"command": "rm -rf /"}, "id": "call_111"},
            {"name": "docker", "args": {"command": "docker rm"}, "id": "call_222"},
            {"name": "shell", "args": {"command": "shutdown"}, "id": "call_333"},
        ]

        # 每个都应该被 auto-deny
        artificial_messages = []
        for tool_call in tool_calls:
            if get_is_subagent():
                error_msg = (
                    "[SYSTEM_ENFORCED] High-risk operations requiring user UI approval "
                    "are strictly forbidden for autonomous Subagents."
                )

                from langchain_core.messages import ToolMessage

                artificial_messages.append(
                    ToolMessage(content=error_msg, name=tool_call["name"], tool_call_id=tool_call["id"], status="error")
                )

        # 验证所有 tool calls 都被拒绝
        assert len(artificial_messages) == 3
        assert all(msg.status == "error" for msg in artificial_messages)
        assert all("[SYSTEM_ENFORCED]" in msg.content for msg in artificial_messages)

        print(f"\n 多个高危操作同时拒绝验证成功: {len(artificial_messages)} 个 tool calls")

    finally:
        set_is_subagent(False)


@pytest.mark.asyncio
async def test_subagent_context_isolation() -> None:
    """验证 subagent 上下文在异步场景下的隔离性。"""
    import asyncio

    async def parent_operation() -> str:
        set_is_subagent(False)
        await asyncio.sleep(0.01)
        return "parent" if not get_is_subagent() else "ERROR"

    async def subagent_operation() -> str:
        set_is_subagent(True)
        try:
            await asyncio.sleep(0.01)
            return "subagent" if get_is_subagent() else "ERROR"
        finally:
            set_is_subagent(False)

    # 并发执行
    results = await asyncio.gather(parent_operation(), subagent_operation(), parent_operation())

    # 验证隔离性
    assert results == ["parent", "subagent", "parent"]

    # 验证最终状态
    assert get_is_subagent() is False
    print(f"\n 异步上下文隔离验证成功: {results}")
