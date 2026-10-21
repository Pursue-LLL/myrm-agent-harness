"""Tests for Resume-Aware Cache Preservation in Context Pipeline"""

from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors import (
    CompressProcessor,
    FilterProcessor,
    SessionNotesProcessor,
    SummarizeProcessor,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.cache_optimizer import ExplicitCacheProcessor


class TestResumeCachePreservation:
    """Test Resume-Aware Cache Preservation behavior in processors"""

    @pytest.fixture
    def base_context(self) -> ProcessorContext:
        """创建基础测试上下文"""
        return ProcessorContext(
            messages=[
                SystemMessage(content="You are a helpful assistant"),
                HumanMessage(content="Hello"),
                AIMessage(content="Hi there!"),
                HumanMessage(content="How are you?"),
            ],
            user_query="How are you?",
            user_id="test-user",
            chat_id="test-chat",
            llm=None,
            metadata={},
        )

    def test_should_skip_for_cache_preservation_normal(self, base_context: ProcessorContext):
        """正常模式（非Resume，非HITL）不跳过"""
        base_context.is_resume = False
        base_context.merged_context = {}

        processor = CompressProcessor()
        assert processor._should_skip_for_cache_preservation(base_context) is False

    def test_should_skip_for_cache_preservation_resume(self, base_context: ProcessorContext):
        """Resume模式下跳过"""
        base_context.is_resume = True
        base_context.merged_context = {}

        processor = CompressProcessor()
        assert processor._should_skip_for_cache_preservation(base_context) is True

    def test_should_skip_for_cache_preservation_hitl_session(self, base_context: ProcessorContext):
        """HITL Session活跃时跳过"""
        base_context.is_resume = False
        base_context.merged_context = {"hitl_session_active": True}

        processor = CompressProcessor()
        assert processor._should_skip_for_cache_preservation(base_context) is True

    def test_should_skip_for_cache_preservation_both(self, base_context: ProcessorContext):
        """Resume + HITL Session同时活跃时跳过"""
        base_context.is_resume = True
        base_context.merged_context = {"hitl_session_active": True}

        processor = CompressProcessor()
        assert processor._should_skip_for_cache_preservation(base_context) is True

    @pytest.mark.asyncio
    async def test_compress_processor_skips_on_resume(self, base_context: ProcessorContext):
        """CompressProcessor在Resume时跳过"""
        base_context.is_resume = True
        original_messages = base_context.messages.copy()

        processor = CompressProcessor()
        result = await processor.process(base_context)

        assert result.messages == original_messages

    @pytest.mark.asyncio
    async def test_filter_processor_skips_on_resume(self, base_context: ProcessorContext):
        """FilterProcessor在Resume时跳过"""
        base_context.is_resume = True
        original_messages = base_context.messages.copy()

        processor = FilterProcessor()
        result = await processor.process(base_context)

        assert result.messages == original_messages

    @pytest.mark.asyncio
    async def test_session_notes_processor_skips_on_resume(self, base_context: ProcessorContext):
        """SessionNotesProcessor在Resume时跳过"""
        base_context.is_resume = True
        original_messages = base_context.messages.copy()

        # Mock SessionNotesManager
        mock_manager = Mock()
        processor = SessionNotesProcessor(manager=mock_manager)
        result = await processor.process(base_context)

        assert result.messages == original_messages

    @pytest.mark.asyncio
    async def test_summarize_processor_skips_on_resume(self, base_context: ProcessorContext):
        """SummarizeProcessor在Resume时跳过"""
        base_context.is_resume = True
        original_messages = base_context.messages.copy()

        processor = SummarizeProcessor()
        result = await processor.process(base_context)

        assert result.messages == original_messages

    @pytest.mark.asyncio
    async def test_compress_processor_skips_on_hitl_session(self, base_context: ProcessorContext):
        """CompressProcessor在HITL Session时跳过"""
        base_context.is_resume = False
        base_context.merged_context = {"hitl_session_active": True}
        original_messages = base_context.messages.copy()

        processor = CompressProcessor()
        result = await processor.process(base_context)

        assert result.messages == original_messages

    @pytest.mark.asyncio
    async def test_explicit_cache_processor_normal_mode(self, base_context: ProcessorContext):
        """ExplicitCacheProcessor在正常模式下设置多个breakpoints"""
        base_context.is_resume = False
        base_context.merged_context = {}

        processor = ExplicitCacheProcessor()
        result = await processor.process(base_context)

        # 检查是否有cache_control
        cache_control_count = sum(
            1
            for msg in result.messages
            if hasattr(msg, "additional_kwargs") and "cache_control" in msg.additional_kwargs
        )
        # 正常模式应该有多个breakpoints
        assert cache_control_count >= 1

    @pytest.mark.asyncio
    async def test_explicit_cache_processor_resume_mode_incremental(self, base_context: ProcessorContext):
        """ExplicitCacheProcessor在Resume模式下只在最后一条消息设置breakpoint"""
        base_context.is_resume = True
        base_context.merged_context = {}

        processor = ExplicitCacheProcessor()
        result = await processor.process(base_context)

        # 检查只有最后一条消息有cache_control
        cache_control_messages = [
            i
            for i, msg in enumerate(result.messages)
            if hasattr(msg, "additional_kwargs") and "cache_control" in msg.additional_kwargs
        ]

        # Resume模式下只有最后一条消息应该有breakpoint
        assert len(cache_control_messages) == 1
        assert cache_control_messages[0] == len(result.messages) - 1

    @pytest.mark.asyncio
    async def test_pipeline_preserves_message_order_on_resume(self, base_context: ProcessorContext):
        """Resume时整个Pipeline保持消息顺序不变"""
        base_context.is_resume = True
        original_messages = [msg.content for msg in base_context.messages]

        # Mock SessionNotesManager
        mock_manager = Mock()

        # 依次通过所有modifying processors
        processors = [
            FilterProcessor(),
            CompressProcessor(),
            SessionNotesProcessor(manager=mock_manager),
            SummarizeProcessor(),
        ]

        context = base_context
        for processor in processors:
            context = await processor.process(context)

        result_messages = [msg.content for msg in context.messages]
        assert result_messages == original_messages

    @pytest.mark.asyncio
    async def test_pipeline_with_hitl_session_active(self, base_context: ProcessorContext):
        """HITL Session活跃时整个Pipeline保持消息不变"""
        base_context.is_resume = False
        base_context.merged_context = {"hitl_session_active": True}
        original_messages = [msg.content for msg in base_context.messages]

        # Mock SessionNotesManager
        mock_manager = Mock()

        # 依次通过所有modifying processors
        processors = [
            FilterProcessor(),
            CompressProcessor(),
            SessionNotesProcessor(manager=mock_manager),
            SummarizeProcessor(),
        ]

        context = base_context
        for processor in processors:
            context = await processor.process(context)

        result_messages = [msg.content for msg in context.messages]
        assert result_messages == original_messages
