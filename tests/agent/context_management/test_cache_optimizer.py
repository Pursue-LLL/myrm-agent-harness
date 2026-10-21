"""显式缓存处理器单元测试

测试覆盖：
1. 参数验证
2. 边界情况（空消息、单条消息）
3. 正常场景（多条消息）
4. 智能断点保留（超限场景）
5. 错误处理
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.cache_optimizer import ExplicitCacheProcessor


class TestExplicitCacheProcessorInit:
    """测试初始化和参数验证"""

    def test_init_with_default_params(self):
        """测试默认参数"""
        processor = ExplicitCacheProcessor()
        assert processor.safe_block_interval == 15
        assert processor.min_message_gap == 6
        assert processor.max_breakpoints == 4

    def test_init_with_custom_params(self):
        """测试自定义参数"""
        processor = ExplicitCacheProcessor(safe_block_interval=10, min_message_gap=3, max_breakpoints=3)
        assert processor.safe_block_interval == 10
        assert processor.min_message_gap == 3
        assert processor.max_breakpoints == 3

    def test_init_invalid_safe_block_interval_too_small(self):
        """测试 safe_block_interval 太小"""
        with pytest.raises(ValueError, match="safe_block_interval 必须是 1-19"):
            ExplicitCacheProcessor(safe_block_interval=0)

    def test_init_invalid_safe_block_interval_too_large(self):
        """测试 safe_block_interval 太大"""
        with pytest.raises(ValueError, match="safe_block_interval 必须是 1-19"):
            ExplicitCacheProcessor(safe_block_interval=20)

    def test_init_invalid_safe_block_interval_not_int(self):
        """测试 safe_block_interval 不是整数"""
        with pytest.raises(ValueError, match="safe_block_interval 必须是 1-19"):
            ExplicitCacheProcessor(safe_block_interval=15.5)

    def test_init_invalid_min_message_gap_too_small(self):
        """测试 min_message_gap 太小"""
        with pytest.raises(ValueError, match="min_message_gap 必须是 1-10"):
            ExplicitCacheProcessor(min_message_gap=0)

    def test_init_invalid_min_message_gap_too_large(self):
        """测试 min_message_gap 太大"""
        with pytest.raises(ValueError, match="min_message_gap 必须是 1-10"):
            ExplicitCacheProcessor(min_message_gap=11)

    def test_init_invalid_max_breakpoints_too_small(self):
        """测试 max_breakpoints 太小"""
        with pytest.raises(ValueError, match="max_breakpoints 必须是 1-4"):
            ExplicitCacheProcessor(max_breakpoints=0)

    def test_init_invalid_max_breakpoints_too_large(self):
        """测试 max_breakpoints 太大"""
        with pytest.raises(ValueError, match="max_breakpoints 必须是 1-4"):
            ExplicitCacheProcessor(max_breakpoints=5)


class TestExplicitCacheProcessorBoundary:
    """测试边界情况"""

    @pytest.mark.asyncio
    async def test_empty_messages(self):
        """测试空消息列表"""
        processor = ExplicitCacheProcessor()
        context = ProcessorContext(messages=[], metadata={}, user_query="test")

        result = await processor.process(context)

        # 空消息列表，不应该有 cache_control
        assert len(result.messages) == 0

    @pytest.mark.asyncio
    async def test_single_message(self):
        """测试单条消息"""
        processor = ExplicitCacheProcessor()
        messages = [SystemMessage(content="You are a helpful assistant")]
        context = ProcessorContext(messages=messages, metadata={}, user_query="test")

        result = await processor.process(context)

        # 单条消息，应该在该消息设置断点
        assert len(result.messages) == 1
        assert result.messages[0].additional_kwargs.get("cache_control") == {"type": "ephemeral"}


class TestExplicitCacheProcessorNormal:
    """测试正常场景"""

    @pytest.mark.asyncio
    async def test_short_conversation(self):
        """测试短对话（< 15 条消息）"""
        processor = ExplicitCacheProcessor()
        messages = [
            SystemMessage(content="You are a helpful assistant"),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
            HumanMessage(content="How are you?"),
            AIMessage(content="I'm doing well, thanks!"),
        ]
        context = ProcessorContext(messages=messages, metadata={}, user_query="test")

        result = await processor.process(context)

        # 检查断点位置
        cache_indices = [i for i, msg in enumerate(result.messages) if msg.additional_kwargs.get("cache_control")]

        # 应该有 2 个断点：System(#0) + 最后消息(#4)
        assert len(cache_indices) == 2
        assert 0 in cache_indices  # System
        assert 4 in cache_indices  # 最后消息

    @pytest.mark.asyncio
    async def test_medium_conversation(self):
        """测试中等对话（15-30 条消息）"""
        processor = ExplicitCacheProcessor()
        messages = [SystemMessage(content="System")]

        # 添加 29 条消息（总共 30 条）
        for i in range(29):
            if i % 2 == 0:
                messages.append(HumanMessage(content=f"User {i // 2}"))
            else:
                messages.append(AIMessage(content=f"AI {i // 2}"))

        context = ProcessorContext(messages=messages, metadata={}, user_query="test")
        result = await processor.process(context)

        cache_indices = [i for i, msg in enumerate(result.messages) if msg.additional_kwargs.get("cache_control")]

        # 应该有 3 个断点：System(#0) + 1个保护(#16) + 最后消息(#29)
        assert len(cache_indices) == 3
        assert 0 in cache_indices  # System
        assert 29 in cache_indices  # 最后消息
        assert any(15 <= idx <= 20 for idx in cache_indices)  # 保护断点


class TestExplicitCacheProcessorSmartRetention:
    """测试智能断点保留"""

    @pytest.mark.asyncio
    async def test_overflow_75_messages(self):
        """测试 75 条消息（6 个断点 → 4 个）"""
        processor = ExplicitCacheProcessor()
        messages = [SystemMessage(content="System")]

        # 添加 74 条消息（总共 75 条）
        for i in range(74):
            if i % 2 == 0:
                messages.append(HumanMessage(content=f"User {i // 2}"))
            else:
                messages.append(AIMessage(content=f"AI {i // 2}"))

        context = ProcessorContext(messages=messages, metadata={}, user_query="test")
        result = await processor.process(context)

        cache_indices = [i for i, msg in enumerate(result.messages) if msg.additional_kwargs.get("cache_control")]

        # 应该只有 4 个断点（智能保留）
        assert len(cache_indices) == 4

        # 第一个必须是 System
        assert cache_indices[0] == 0

        # 最后一个必须是最后消息
        assert cache_indices[-1] == 74

        # 中间应该有 2 个保护断点
        middle_bps = cache_indices[1:-1]
        assert len(middle_bps) == 2

    @pytest.mark.asyncio
    async def test_overflow_100_messages(self):
        """测试 100 条消息（8 个断点 → 4 个）"""
        processor = ExplicitCacheProcessor()
        messages = [SystemMessage(content="System")]

        # 添加 99 条消息（总共 100 条）
        for i in range(99):
            if i % 2 == 0:
                messages.append(HumanMessage(content=f"User {i // 2}"))
            else:
                messages.append(AIMessage(content=f"AI {i // 2}"))

        context = ProcessorContext(messages=messages, metadata={}, user_query="test")
        result = await processor.process(context)

        cache_indices = [i for i, msg in enumerate(result.messages) if msg.additional_kwargs.get("cache_control")]

        # 应该只有 4 个断点（智能保留）
        assert len(cache_indices) == 4
        assert cache_indices[0] == 0  # System
        assert cache_indices[-1] == 99  # 最后消息


class TestExplicitCacheProcessorErrorHandling:
    """测试错误处理"""

    @pytest.mark.asyncio
    async def test_no_system_message(self):
        """测试没有 System 消息的情况"""
        processor = ExplicitCacheProcessor()
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi!"),
        ]
        context = ProcessorContext(messages=messages, metadata={}, user_query="test")

        result = await processor.process(context)

        # 即使没有 System，也应该至少缓存最后一条消息
        cache_indices = [i for i, msg in enumerate(result.messages) if msg.additional_kwargs.get("cache_control")]

        assert len(cache_indices) >= 1
        assert cache_indices[-1] == 1  # 最后消息

    @pytest.mark.asyncio
    async def test_compress_boundary_integration(self):
        """测试与压缩边界的集成"""
        processor = ExplicitCacheProcessor()
        messages = [SystemMessage(content="System")]

        # 添加 49 条消息
        for i in range(49):
            if i % 2 == 0:
                messages.append(HumanMessage(content=f"User {i // 2}"))
            else:
                messages.append(AIMessage(content=f"AI {i // 2}"))

        # 模拟压缩边界在第 25 条消息
        context = ProcessorContext(messages=messages, metadata={"last_compress_boundary_index": 25}, user_query="test")
        result = await processor.process(context)

        cache_indices = [i for i, msg in enumerate(result.messages) if msg.additional_kwargs.get("cache_control")]

        # 应该包含压缩边界断点（如果距离合适）
        assert 0 in cache_indices  # System
        assert 49 in cache_indices  # 最后消息
        # 可能包含压缩边界（取决于与其他断点的距离）


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
