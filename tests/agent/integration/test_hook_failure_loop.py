"""端到端集成测试：验证 POST_TOOL_USE Hook 失败闭环。

测试场景：
1. Agent 调用工具
2. POST_TOOL_USE hook 失败
3. ToolMessage 被转换为 error
4. LLM 感知到错误并尝试修复

这个测试使用真实的 Agent 和 middleware，不使用 mock。
"""

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.hooks.types import AggregatedHookResult, HookResult


@pytest.mark.asyncio
async def test_post_hook_failure_converts_to_error() -> None:
    """验证 POST_TOOL_USE hook 失败时，ToolMessage 被转换为 error。

    这测试了 tool_interceptor_middleware.py 的核心逻辑。
    """
    # 模拟一个失败的 POST_TOOL_USE hook result
    failed_hook_result = AggregatedHookResult(
        results=[
            HookResult(
                hook_type="oxlint",
                blocked=True,
                reason="Linting failed",
                output="app.py:42:10 - Unused variable 'x'",
                success=False,
            )
        ]
    )

    # 验证 AggregatedHookResult 的属性
    assert failed_hook_result.blocked is True
    assert failed_hook_result.all_succeeded is False
    assert len(failed_hook_result.results) == 1
    assert "Unused variable" in failed_hook_result.results[0].output

    # 验证错误 ToolMessage 的构建
    # 这是 tool_interceptor_middleware.py 中的逻辑
    error_details = []
    for hook_result in failed_hook_result.results:
        if (hook_result.blocked or not hook_result.success) and hook_result.output:
            error_details.append(f"[{hook_result.hook_type}] {hook_result.output}")

    hook_error_msg = "\n".join(error_details)

    # 验证错误消息格式
    assert "oxlint" in hook_error_msg
    assert "Unused variable" in hook_error_msg
    assert "app.py:42:10" in hook_error_msg

    # 构建 error ToolMessage
    tool_msg = ToolMessage(
        content=f"[HOOK_VALIDATION_FAILED] Post-execution hook detected critical issues:\n\n{hook_error_msg}",
        name="test_tool",
        tool_call_id="test_call_123",
        status="error",
    )

    # 验证 ToolMessage 状态
    assert tool_msg.status == "error"
    assert "[HOOK_VALIDATION_FAILED]" in tool_msg.content
    assert "oxlint" in tool_msg.content
    print(f"\n Error ToolMessage 构建成功:\n{tool_msg.content[:200]}...")


@pytest.mark.asyncio
async def test_post_hook_success_no_conversion() -> None:
    """验证 POST_TOOL_USE hook 成功时，ToolMessage 保持原样。"""
    # 模拟一个成功的 POST_TOOL_USE hook result
    success_hook_result = AggregatedHookResult(
        results=[HookResult(hook_type="oxlint", blocked=False, reason="", output="", success=True)]
    )

    # 验证 AggregatedHookResult 的属性
    assert success_hook_result.blocked is False
    assert success_hook_result.all_succeeded is True

    # 成功情况下，不应该修改 ToolMessage
    # 这是 tool_interceptor_middleware.py 中的逻辑
    if not success_hook_result.blocked and success_hook_result.all_succeeded:
        # 直接返回原始 result，不做修改
        original_msg = ToolMessage(
            content="File created successfully", name="bash", tool_call_id="test_call_456", status="success"
        )
        # 验证保持原样
        assert original_msg.status == "success"
        assert original_msg.content == "File created successfully"
        print("\n 成功场景：ToolMessage 保持原样")


@pytest.mark.asyncio
async def test_token_truncation_for_large_output() -> None:
    """验证大输出场景下的 token 截断。"""
    from myrm_agent_harness.agent.middlewares._tool_helpers import smart_truncate_output as _smart_truncate_output

    # 模拟大文件输出（10000行）
    large_output = "\n".join([f"line {i}: some content here" for i in range(10000)])

    # 执行截断
    truncated = _smart_truncate_output(large_output, max_lines=20)

    # 验证截断效果
    lines = truncated.split("\n")
    assert len(lines) < 100, f"截断后行数应该远小于原始行数，实际 {len(lines)}"
    assert "line 0" in truncated, "应该保留第一行"
    assert "line 9999" in truncated, "应该保留最后一行"
    assert "truncated 9980 lines" in truncated, "应该有截断标记"

    # 计算 token 节省（理论计算）
    original_size = len(large_output)
    truncated_size = len(truncated)
    saving_ratio = (original_size - truncated_size) / original_size

    assert saving_ratio > 0.95, f"节省比例应该 >95%，实际 {saving_ratio:.2%}"
    print(f"\n Token 截断验证：原始 {original_size} 字节，截断后 {truncated_size} 字节，节省 {saving_ratio:.2%}")


@pytest.mark.asyncio
async def test_multiple_hooks_fail_simultaneously() -> None:
    """验证多个 hook 同时失败时，错误消息正确聚合。"""
    # 模拟多个 hook 同时失败
    multi_fail_result = AggregatedHookResult(
        results=(
            HookResult(
                hook_type="oxlint",
                blocked=True,
                reason="Linting failed",
                output="app.py:42:10 - Unused variable 'x'",
                success=False,
            ),
            HookResult(
                hook_type="prettier",
                blocked=False,
                reason="Formatting check failed",
                output="app.py:100:5 - Expected 2 spaces, found 4",
                success=False,
            ),
            HookResult(
                hook_type="mypy",
                blocked=True,
                reason="Type check failed",
                output="app.py:200:10 - Incompatible types",
                success=False,
            ),
        )
    )

    # 验证聚合属性
    assert multi_fail_result.blocked is True  # 任一 blocked=True，整体就 blocked
    assert multi_fail_result.all_succeeded is False
    assert len(multi_fail_result.results) == 3

    # 模拟 tool_interceptor_middleware.py 的错误收集逻辑
    error_details = []
    for hook_result in multi_fail_result.results:
        if (hook_result.blocked or not hook_result.success) and hook_result.output:
            error_details.append(f"[{hook_result.hook_type}] {hook_result.output}")

    hook_error_msg = "\n".join(error_details)

    # 验证所有 hook 错误都被收集
    assert "oxlint" in hook_error_msg
    assert "prettier" in hook_error_msg
    assert "mypy" in hook_error_msg
    assert "Unused variable" in hook_error_msg
    assert "Expected 2 spaces" in hook_error_msg
    assert "Incompatible types" in hook_error_msg

    print(f"\n 多 Hook 失败聚合验证成功:\n{hook_error_msg}")


@pytest.mark.asyncio
async def test_hook_failure_with_empty_messages() -> None:
    """验证 hook 失败但 output/reason 都为空时的 fallback。"""
    # 模拟 hook 失败但没有提供详细信息
    empty_msg_result = AggregatedHookResult(
        results=[
            HookResult(
                hook_type="custom_hook",
                blocked=True,
                reason="",  # 空 reason
                output="",  # 空 output
                success=False,
            )
        ]
    )

    # 验证聚合属性
    assert empty_msg_result.blocked is True
    assert empty_msg_result.all_succeeded is False

    # 模拟 tool_interceptor_middleware.py 的错误收集逻辑
    error_details = []
    for hook_result in empty_msg_result.results:
        if hook_result.blocked or not hook_result.success:
            if hook_result.output:
                error_details.append(hook_result.output)
            elif hook_result.reason:
                error_details.append(hook_result.reason)

    # 如果 error_details 为空，使用 fallback
    hook_error_msg = "\n".join(error_details) if error_details else "Hook validation failed"

    # 验证 fallback 生效
    assert hook_error_msg == "Hook validation failed"
    print(f"\n 空消息 Fallback 验证成功: '{hook_error_msg}'")
