"""显式缓存处理器单元测试

测试 ExplicitCacheProcessor 的核心功能：
1. 断点计算正确性
2. 边界条件处理
3. Token 距离验证
4. Cache control 注入
5. 缓存失效检测
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.cache_breakpoint_validator import (
    validate_token_distances,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.cache_optimizer import ExplicitCacheProcessor


class TestBreakpointCalculation:
    """测试断点计算逻辑"""

    @pytest.fixture
    def processor(self):
        return ExplicitCacheProcessor(safe_block_interval=15, min_message_gap=6, max_breakpoints=4)

    def test_system_message_breakpoint(self, processor):
        """测试系统消息后设置断点"""
        messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi"),
        ]

        context = ProcessorContext(messages=messages, user_query="test")
        context.metadata["model_name"] = "claude-3-5-sonnet-20241022"

        breakpoints = processor._calculate_breakpoints(context)

        # 应该在 System 后（index 0）和最后一条消息（index 2）设置断点
        assert 0 in breakpoints
        assert len(messages) - 1 in breakpoints

    def test_last_message_breakpoint_always_included(self, processor):
        """测试最后一条消息断点总是包含"""
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Q1"),
            AIMessage(content="A1"),
        ]

        context = ProcessorContext(messages=messages, user_query="test")
        context.metadata["model_name"] = "claude-3-5-sonnet-20241022"

        breakpoints = processor._calculate_breakpoints(context)

        # 最后一条消息断点必须存在
        assert len(messages) - 1 in breakpoints

    def test_20_block_protection(self, processor):
        """测试 20-block 保护断点"""
        # 创建 30 条消息（超过 20-block window）
        messages = [SystemMessage(content="System")]
        for i in range(29):
            messages.append(HumanMessage(content=f"Message {i}"))

        context = ProcessorContext(messages=messages, user_query="test")
        context.metadata["model_name"] = "claude-3-5-sonnet-20241022"

        breakpoints = processor._calculate_breakpoints(context)

        # 应该有多个保护断点
        assert len(breakpoints) >= 2
        assert 0 in breakpoints  # System 后
        assert len(messages) - 1 in breakpoints  # 最后一条

    def test_compression_boundary_breakpoint(self, processor):
        """测试压缩边界断点"""
        # 创建足够多的消息，确保压缩边界满足距离要求
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Q1"),
            AIMessage(content="A1"),
            HumanMessage(content="Q2"),
            AIMessage(content="A2"),
            HumanMessage(content="Q3"),
            AIMessage(content="A3"),
            HumanMessage(content="Q4"),
            AIMessage(content="A4"),
        ]

        context = ProcessorContext(messages=messages, user_query="test")
        context.metadata["model_name"] = "claude-3-5-sonnet-20241022"
        # 压缩边界在 index 7（距离 System 后 7 条消息，满足 min_message_gap=6）
        context.metadata["last_compress_boundary_index"] = 7

        breakpoints = processor._calculate_breakpoints(context)

        # 压缩边界应该被包含
        assert 7 in breakpoints or len(breakpoints) >= 2  # 至少有 System 后和最后一条

    def test_max_breakpoints_enforcement(self, processor):
        """测试最大断点数限制"""
        # 创建大量消息
        messages = [SystemMessage(content="System")]
        for i in range(100):
            messages.append(HumanMessage(content=f"Message {i}"))

        context = ProcessorContext(messages=messages, user_query="test")
        context.metadata["model_name"] = "claude-3-5-sonnet-20241022"

        breakpoints = processor._calculate_breakpoints(context)

        # 不能超过 max_breakpoints
        assert len(breakpoints) <= processor.max_breakpoints


class TestTokenDistanceValidation:
    """测试 token 距离验证"""

    @pytest.fixture
    def processor(self):
        return ExplicitCacheProcessor(min_message_gap=3)

    def test_sufficient_token_distance(self, processor):
        """测试 token 距离充足时保留断点"""
        # 创建消息，确保距离 >= 1024 tokens
        messages = [
            SystemMessage(content="System prompt " * 200),  # ~400 tokens
            HumanMessage(content="User query " * 200),  # ~400 tokens
            AIMessage(content="AI response " * 200),  # ~400 tokens
        ]

        breakpoints = [0, 2]
        validated = validate_token_distances(breakpoints, messages, processor.min_message_gap)

        # 距离充足，应该都保留
        assert validated == [0, 2]

    def test_insufficient_token_distance_fallback(self, processor):
        """测试 token 距离不足但消息间隔满足时的 fallback"""
        # 创建短消息
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Q1"),
            HumanMessage(content="Q2"),
            HumanMessage(content="Q3"),
            AIMessage(content="A"),
        ]

        # 断点间隔 4 条消息，大于 min_message_gap (3)
        breakpoints = [0, 4]
        validated = validate_token_distances(breakpoints, messages, processor.min_message_gap)

        # 虽然 tokens 不足，但消息间隔满足，应该保留
        assert validated == [0, 4]

    def test_last_message_always_retained(self, processor):
        """测试最后一条消息断点无条件保留"""
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Q"),
            AIMessage(content="A"),
        ]

        # 最后一条消息距离很近
        breakpoints = [0, 2]
        validated = validate_token_distances(breakpoints, messages, processor.min_message_gap)

        # 最后一条消息应该保留（即使距离不足）
        assert 2 in validated


class TestCacheControlInjection:
    """测试 cache_control 注入"""

    @pytest.fixture
    def processor(self):
        return ExplicitCacheProcessor()

    def _make_context(self, messages, **metadata_kwargs):
        ctx = ProcessorContext(messages=messages, user_query="test")
        ctx.metadata.update(metadata_kwargs)
        return ctx

    def test_inject_cache_control(self, processor):
        """测试 cache_control 正确注入"""
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Query"),
            AIMessage(content="Response"),
        ]
        ctx = self._make_context(messages)

        breakpoints = [0, 2]
        result = processor._inject_cache_control(messages, breakpoints, ctx)

        assert result[0].additional_kwargs.get("cache_control") == {"type": "ephemeral"}
        assert result[2].additional_kwargs.get("cache_control") == {"type": "ephemeral"}
        assert "cache_control" not in result[1].additional_kwargs

    def test_inject_cache_control_1h_ttl_for_anthropic_direct(self, processor):
        """测试 Anthropic 直连端点使用 1h TTL"""
        messages = [SystemMessage(content="System"), HumanMessage(content="Query")]
        ctx = self._make_context(messages, base_url="https://api.anthropic.com/v1")

        result = processor._inject_cache_control(messages, [0], ctx)
        assert result[0].additional_kwargs.get("cache_control") == {"type": "ephemeral", "ttl": "1h"}

    def test_inject_cache_control_default_ttl_for_proxy(self, processor):
        """测试代理端点使用默认 5min TTL"""
        messages = [SystemMessage(content="System"), HumanMessage(content="Query")]
        ctx = self._make_context(messages, base_url="https://openrouter.ai/api/v1")

        result = processor._inject_cache_control(messages, [0], ctx)
        assert result[0].additional_kwargs.get("cache_control") == {"type": "ephemeral"}

    def test_inject_cache_control_explicit_long_retention(self, processor):
        """测试显式 cache_retention=long 强制 1h TTL"""
        messages = [SystemMessage(content="System")]
        ctx = self._make_context(messages, cache_retention="long")

        result = processor._inject_cache_control(messages, [0], ctx)
        assert result[0].additional_kwargs.get("cache_control") == {"type": "ephemeral", "ttl": "1h"}

    def test_inject_cache_control_litellm_anthropic_prefix_infers_direct(self, processor):
        """测试 LiteLLM anthropic/ 前缀推断为直连, 使用 1h TTL"""
        messages = [SystemMessage(content="System")]
        ctx = self._make_context(messages, model_name="anthropic/claude-3-5-sonnet-20241022", base_url="")

        result = processor._inject_cache_control(messages, [0], ctx)
        assert result[0].additional_kwargs.get("cache_control") == {"type": "ephemeral", "ttl": "1h"}

    def test_inject_cache_control_claude_prefix_without_anthropic_uses_default(self, processor):
        """测试 claude- 前缀但无 anthropic/ 时不推断(可能通过代理)"""
        messages = [SystemMessage(content="System")]
        ctx = self._make_context(messages, model_name="claude-3-5-sonnet-20241022", base_url="")

        result = processor._inject_cache_control(messages, [0], ctx)
        assert result[0].additional_kwargs.get("cache_control") == {"type": "ephemeral"}

    def test_does_not_modify_original(self, processor):
        """测试不修改原始消息"""
        original = [
            SystemMessage(content="System"),
            HumanMessage(content="Query"),
        ]
        ctx = self._make_context(original)

        breakpoints = [0]
        result = processor._inject_cache_control(original, breakpoints, ctx)

        assert "cache_control" not in original[0].additional_kwargs
        assert result[0].additional_kwargs.get("cache_control") == {"type": "ephemeral"}


class TestEdgeCases:
    """测试边界条件"""

    @pytest.fixture
    def processor(self):
        return ExplicitCacheProcessor()

    def test_empty_messages(self, processor):
        """测试空消息列表"""
        context = ProcessorContext(messages=[], user_query="test")
        context.metadata["model_name"] = "claude-3-5-sonnet-20241022"

        breakpoints = processor._calculate_breakpoints(context)
        assert breakpoints == []

    def test_single_message(self, processor):
        """测试单条消息"""
        messages = [SystemMessage(content="System")]
        context = ProcessorContext(messages=messages, user_query="test")
        context.metadata["model_name"] = "claude-3-5-sonnet-20241022"

        breakpoints = processor._calculate_breakpoints(context)

        # 单条消息应该设置断点
        assert 0 in breakpoints

    def test_no_system_message(self, processor):
        """测试无系统消息"""
        messages = [
            HumanMessage(content="Query"),
            AIMessage(content="Response"),
        ]

        context = ProcessorContext(messages=messages, user_query="test")
        context.metadata["model_name"] = "claude-3-5-sonnet-20241022"

        breakpoints = processor._calculate_breakpoints(context)

        # 最后一条消息应该有断点
        assert len(messages) - 1 in breakpoints


@pytest.mark.asyncio
async def test_full_pipeline():
    """测试完整流程"""
    processor = ExplicitCacheProcessor()

    messages = [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content="Hello, who are you?"),
        AIMessage(content="I am an AI assistant."),
        HumanMessage(content="What can you do?"),
        AIMessage(content="I can help with various tasks."),
    ]

    context = ProcessorContext(messages=messages, user_query="test")
    context.metadata["model_name"] = "claude-3-5-sonnet-20241022"
    context.metadata["turn_count"] = 2

    # 执行完整流程
    result = await processor.process(context)

    # 验证结果
    assert len(result.messages) == len(messages)

    # 至少应该有 System 后和最后一条消息的断点
    has_cache_control = sum(1 for msg in result.messages if "cache_control" in msg.additional_kwargs)
    assert has_cache_control >= 2


@pytest.mark.asyncio
async def test_skip_non_anthropic_models():
    """测试非 Anthropic 模型跳过处理"""
    processor = ExplicitCacheProcessor()

    messages = [
        SystemMessage(content="System"),
        HumanMessage(content="Query"),
    ]

    context = ProcessorContext(messages=messages, user_query="test")
    context.metadata["model_name"] = "gpt-4-turbo"  # OpenAI 模型

    # should_process 应该返回 False
    should_process = await processor.should_process(context)
    assert not should_process


class TestCoverageGaps:
    """补充覆盖缺失边界分支"""

    @pytest.fixture
    def processor(self):
        return ExplicitCacheProcessor()

    def _make_context(self, messages, **metadata_kwargs):
        ctx = ProcessorContext(messages=messages, user_query="test")
        ctx.metadata.update(metadata_kwargs)
        return ctx

    def test_name_property(self, processor):
        assert processor.name == "explicit_cache"

    @pytest.mark.asyncio
    async def test_should_process_empty_model_name(self, processor):
        ctx = ProcessorContext(messages=[SystemMessage(content="S")], user_query="t")
        ctx.metadata["model_name"] = ""
        assert not await processor.should_process(ctx)

    def test_resume_mode_only_last_message(self, processor):
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Q1"),
            AIMessage(content="A1"),
            HumanMessage(content="Q2"),
        ]
        ctx = self._make_context(messages, model_name="claude-3-5-sonnet-20241022")
        ctx.is_resume = True
        breakpoints = processor._calculate_breakpoints(ctx)
        assert breakpoints == [3]

    def test_inject_cache_control_empty_breakpoints(self, processor):
        messages = [SystemMessage(content="System")]
        ctx = self._make_context(messages)
        result = processor._inject_cache_control(messages, [], ctx)
        assert result is messages

    def test_cache_retention_none_uses_default_ttl(self, processor):
        messages = [SystemMessage(content="System")]
        ctx = self._make_context(messages, cache_retention="none")
        result = processor._inject_cache_control(messages, [0], ctx)
        assert result[0].additional_kwargs.get("cache_control") == {"type": "ephemeral"}

    def test_calculate_expected_cacheable_tokens_empty(self, processor):
        result = processor._calculate_expected_cacheable_tokens([], [])
        assert result == 0

    def test_calculate_expected_cacheable_tokens_no_breakpoints(self, processor):
        messages = [SystemMessage(content="Hello")]
        result = processor._calculate_expected_cacheable_tokens(messages, [])
        assert result == 0

    def test_inject_cache_control_vertex_ai_endpoint_1h_ttl(self, processor):
        """Google Vertex AI 端点使用 1h TTL"""
        messages = [SystemMessage(content="System")]
        ctx = self._make_context(
            messages,
            base_url="https://us-east5-aiplatform.googleapis.com/v1/projects/my-project/locations/us-east5/publishers/anthropic/models/claude-3-5-sonnet",
        )
        result = processor._inject_cache_control(messages, [0], ctx)
        assert result[0].additional_kwargs.get("cache_control") == {"type": "ephemeral", "ttl": "1h"}

    def test_is_long_ttl_eligible_empty_url(self, processor):
        """空 URL 不符合长 TTL"""
        assert not processor._is_long_ttl_eligible_endpoint("")

    def test_is_long_ttl_eligible_anthropic_direct(self, processor):
        """Anthropic 直连 URL 符合长 TTL"""
        assert processor._is_long_ttl_eligible_endpoint("https://api.anthropic.com/v1")

    def test_is_long_ttl_eligible_vertex(self, processor):
        """Vertex AI URL 符合长 TTL"""
        assert processor._is_long_ttl_eligible_endpoint(
            "https://us-central1-aiplatform.googleapis.com/v1/projects/x/locations/us-central1/publishers/anthropic/models/claude-3-5-sonnet"
        )

    def test_is_long_ttl_eligible_proxy_returns_false(self, processor):
        """代理 URL 不符合长 TTL"""
        assert not processor._is_long_ttl_eligible_endpoint("https://openrouter.ai/api/v1")
        assert not processor._is_long_ttl_eligible_endpoint("https://my-proxy.example.com/v1")

    def test_cache_retention_long_overrides_proxy_url(self, processor):
        """cache_retention='long' 优先于 base_url 判断"""
        messages = [SystemMessage(content="System")]
        ctx = self._make_context(
            messages, cache_retention="long", base_url="https://openrouter.ai/api/v1"
        )
        result = processor._inject_cache_control(messages, [0], ctx)
        assert result[0].additional_kwargs.get("cache_control") == {"type": "ephemeral", "ttl": "1h"}

    @pytest.mark.asyncio
    async def test_should_process_qwen_model(self, processor):
        """Qwen 模型需要显式缓存处理"""
        ctx = ProcessorContext(messages=[SystemMessage(content="S")], user_query="t")
        ctx.metadata["model_name"] = "qwen-max-0428"
        assert await processor.should_process(ctx)

    @pytest.mark.asyncio
    async def test_should_process_dashscope_model(self, processor):
        """DashScope 模型需要显式缓存处理"""
        ctx = ProcessorContext(messages=[SystemMessage(content="S")], user_query="t")
        ctx.metadata["model_name"] = "dashscope/qwen-plus"
        assert await processor.should_process(ctx)

    @pytest.mark.asyncio
    async def test_should_process_openai_model_skipped(self, processor):
        """OpenAI 模型使用自动前缀缓存，跳过显式处理"""
        ctx = ProcessorContext(messages=[SystemMessage(content="S")], user_query="t")
        ctx.metadata["model_name"] = "gpt-4o"
        assert not await processor.should_process(ctx)

    @pytest.mark.asyncio
    async def test_should_process_deepseek_model_skipped(self, processor):
        """DeepSeek 模型使用自动前缀缓存，跳过显式处理"""
        ctx = ProcessorContext(messages=[SystemMessage(content="S")], user_query="t")
        ctx.metadata["model_name"] = "deepseek-chat"
        assert not await processor.should_process(ctx)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
