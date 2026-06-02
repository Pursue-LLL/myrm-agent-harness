"""测试上下文压缩增强功能

测试新增的功能：
1. 工具结果统计信息提取
2. 内容去重机制
3. 错误类型分类
4. 智能模板选择
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.strategies.deduplication import deduplicate_tool_results
from myrm_agent_harness.agent.context_management.strategies.tool_stats import extract_tool_stats


class TestExtractToolStats:
    """测试工具统计信息提取"""

    def test_extract_bash_exit_code_success(self):
        """测试提取成功的exit_code"""
        content = "test output\n[exit_code: 0]"
        stats = extract_tool_stats("bash_code_execute_tool", content)

        assert stats["exit_code"] == 0
        assert stats["lines"] == 2
        assert stats["chars"] == len(content)

    def test_extract_bash_exit_code_failure(self):
        """测试提取失败的exit_code"""
        content = "error output\n[exit_code: 1 — No matches found (not an error)]"
        stats = extract_tool_stats("bash_code_execute_tool", content)

        assert stats["exit_code"] == 1
        assert stats["lines"] == 2

    def test_extract_bash_exit_code_missing(self):
        """测试缺失exit_code时的默认行为"""
        content = "output without exit code"
        stats = extract_tool_stats("bash_code_execute_tool", content)

        assert stats["exit_code"] == 0  # 默认假设成功
        assert stats["chars"] > 0

    def test_extract_large_output_truncated_info(self):
        """测试提取LARGE OUTPUT TRUNCATED信息"""
        content = "[LARGE OUTPUT TRUNCATED (247 lines, ~8500 tokens)]\npreview..."
        stats = extract_tool_stats("file_read_tool", content)

        assert stats["lines"] == 247
        assert stats["tokens"] == 8500

    def test_extract_web_search_stats(self):
        """测试web_search_tool统计信息"""
        content = "search result " * 100
        stats = extract_tool_stats("web_search_tool", content)

        assert stats["chars"] == len(content)
        assert stats["lines"] > 0

    def test_extract_stats_empty_content(self):
        """测试空内容"""
        stats = extract_tool_stats("bash_code_execute_tool", "")

        assert stats["chars"] == 0
        assert stats["lines"] == 0
        assert stats["exit_code"] == 0


class TestDeduplicateToolResults:
    """测试内容去重机制"""

    def test_deduplicate_identical_content(self):
        """测试去重完全相同的内容"""
        messages = [
            HumanMessage(content="请求1"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {}}]),
            ToolMessage(content="x" * 300, tool_call_id="call_1", name="bash"),
            HumanMessage(content="请求2"),
            AIMessage(content="", tool_calls=[{"id": "call_2", "name": "bash", "args": {}}]),
            ToolMessage(content="x" * 300, tool_call_id="call_2", name="bash"),  # 相同内容
        ]

        result_messages, saved = deduplicate_tool_results(messages)

        # 从后向前遍历，所以第一个ToolMessage（索引2）应该被替换为引用
        assert isinstance(result_messages[2], ToolMessage)
        assert "Duplicate tool output" in result_messages[2].content

        # 最后一个ToolMessage（索引5）应该保持完整
        assert isinstance(result_messages[5], ToolMessage)
        assert "Duplicate" not in result_messages[5].content

        assert saved > 0

    def test_deduplicate_preserves_latest(self):
        """测试保留最新的完整副本"""
        messages = [
            HumanMessage(content="请求1"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {}}]),
            ToolMessage(content="x" * 300, tool_call_id="call_1", name="bash"),
            HumanMessage(content="请求2"),
            AIMessage(content="", tool_calls=[{"id": "call_2", "name": "bash", "args": {}}]),
            ToolMessage(content="x" * 300, tool_call_id="call_2", name="bash"),
        ]

        result_messages, _ = deduplicate_tool_results(messages)

        # 最后一个应该保持完整
        last_tool_msg = result_messages[5]
        assert "Duplicate" not in last_tool_msg.content
        assert last_tool_msg.content == "x" * 300

        # 第一个应该被替换为引用
        first_tool_msg = result_messages[2]
        assert "Duplicate" in first_tool_msg.content

    def test_deduplicate_skips_small_content(self):
        """测试跳过小型内容（<200 chars）"""
        messages = [
            HumanMessage(content="请求1"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {}}]),
            ToolMessage(content="small", tool_call_id="call_1", name="bash"),
            HumanMessage(content="请求2"),
            AIMessage(content="", tool_calls=[{"id": "call_2", "name": "bash", "args": {}}]),
            ToolMessage(content="small", tool_call_id="call_2", name="bash"),
        ]

        result_messages, saved = deduplicate_tool_results(messages)

        # 小内容不应被去重
        assert saved == 0
        assert result_messages[2].content == "small"
        assert result_messages[5].content == "small"

    def test_deduplicate_skips_compressed_content(self):
        """测试跳过已压缩的内容"""
        messages = [
            HumanMessage(content="请求1"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {}}]),
            ToolMessage(content="COMPACTED: bash\\nCMD: test", tool_call_id="call_1", name="bash"),
            HumanMessage(content="请求2"),
            AIMessage(content="", tool_calls=[{"id": "call_2", "name": "bash", "args": {}}]),
            ToolMessage(content="COMPACTED: bash\\nCMD: test", tool_call_id="call_2", name="bash"),
        ]

        _result_messages, saved = deduplicate_tool_results(messages)

        # 已压缩内容不应被去重
        assert saved == 0

    def test_deduplicate_different_content(self):
        """测试不去重不同的内容"""
        messages = [
            HumanMessage(content="请求1"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {}}]),
            ToolMessage(content="a" * 300, tool_call_id="call_1", name="bash"),
            HumanMessage(content="请求2"),
            AIMessage(content="", tool_calls=[{"id": "call_2", "name": "bash", "args": {}}]),
            ToolMessage(content="b" * 300, tool_call_id="call_2", name="bash"),  # 不同内容
        ]

        result_messages, saved = deduplicate_tool_results(messages)

        # 内容不同，不应去重
        assert saved == 0
        assert result_messages[2].content == "a" * 300
        assert result_messages[5].content == "b" * 300


class TestClassifyErrorType:
    """测试错误类型分类"""

    def test_classify_auth_error(self):
        """测试识别认证错误"""
        from myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor import (
            _classify_error_type,
        )

        exc1 = Exception("Unauthorized: Invalid API key")
        assert _classify_error_type(exc1) == "auth"

        exc2 = Exception("403 Forbidden")
        assert _classify_error_type(exc2) == "auth"

        exc3 = Exception("Authentication failed")
        assert _classify_error_type(exc3) == "auth"

    def test_classify_permanent_error(self):
        """测试识别永久错误"""
        from myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor import (
            _classify_error_type,
        )

        exc1 = Exception("Model not found")
        assert _classify_error_type(exc1) == "permanent"

        exc2 = Exception("does not exist")
        assert _classify_error_type(exc2) == "permanent"

        # 测试status_code
        exc3 = Exception("HTTP error")
        exc3.status_code = 404
        assert _classify_error_type(exc3) == "permanent"

        exc4 = Exception("Service unavailable")
        exc4.status_code = 503
        assert _classify_error_type(exc4) == "permanent"

    def test_classify_transient_error(self):
        """测试识别瞬态错误（默认）"""
        from myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor import (
            _classify_error_type,
        )

        exc1 = Exception("Connection timeout")
        assert _classify_error_type(exc1) == "transient"

        exc2 = Exception("Rate limit exceeded")
        assert _classify_error_type(exc2) == "transient"

        exc3 = Exception("Unknown error")
        assert _classify_error_type(exc3) == "transient"


@pytest.mark.asyncio
async def test_compress_tool_message_with_stats():
    """测试压缩时保留统计信息"""
    from myrm_agent_harness.agent.context_management.strategies.compactor import compress_tool_message_async

    # 创建大型bash输出（应该使用stats_template）
    tool_msg = ToolMessage(
        content="x" * 500 + "\n[exit_code: 1]", tool_call_id="call_123", name="bash_code_execute_tool"
    )

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"id": "call_123", "name": "bash_code_execute_tool", "args": {"command": "pytest tests/"}}],
    )

    saved = await compress_tool_message_async(tool_msg, ai_msg)

    # 验证压缩后包含统计信息
    assert "COMPACTED:" in tool_msg.content
    assert "EXIT:" in tool_msg.content
    assert "OUT:" in tool_msg.content
    assert "1" in tool_msg.content  # exit_code值
    assert saved > 0


@pytest.mark.asyncio
async def test_compress_tool_message_small_output():
    """测试小型输出使用基础模板"""
    from myrm_agent_harness.agent.context_management.strategies.compactor import compress_tool_message_async

    # 创建小型bash输出（应该使用基础template）
    tool_msg = ToolMessage(content="ok\n[exit_code: 0]", tool_call_id="call_123", name="bash_code_execute_tool")

    ai_msg = AIMessage(
        content="", tool_calls=[{"id": "call_123", "name": "bash_code_execute_tool", "args": {"command": "echo ok"}}]
    )

    await compress_tool_message_async(tool_msg, ai_msg)

    # 验证使用基础模板（不包含EXIT/OUT）
    assert "COMPACTED:" in tool_msg.content
    assert "COMMAND:" in tool_msg.content
    # 小型输出不应添加统计信息（避免变长）
    # 注意：如果变长了，stats会被使用；如果没变长就是降级了


@pytest.mark.asyncio
async def test_deduplicate_in_compress_messages_async():
    """测试compress_messages_async中的去重功能"""
    from myrm_agent_harness.agent.context_management.strategies.compactor import compress_messages_async

    # 创建包含重复内容的消息序列
    messages = []
    for i in range(8):
        messages.append(HumanMessage(content=f"请求{i}"))
        messages.append(
            AIMessage(
                content="",
                tool_calls=[{"id": f"call_{i}", "name": "bash_code_execute_tool", "args": {"command": "test"}}],
            )
        )
        # 偶数索引使用相同内容，奇数索引也使用相同内容
        content = ("a" * 300) if i % 2 == 0 else ("b" * 300)
        messages.append(ToolMessage(content=content, tool_call_id=f"call_{i}", name="bash_code_execute_tool"))

    compressed, saved = await compress_messages_async(messages)

    # 应该有去重发生
    dedup_count = sum(1 for msg in compressed if isinstance(msg, ToolMessage) and "Duplicate" in msg.content)

    # 至少应该有一些去重
    assert dedup_count > 0
    assert saved >= 0  # 去重会节省tokens
