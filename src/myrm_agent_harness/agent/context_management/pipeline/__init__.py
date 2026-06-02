"""Pipeline module.

提供 Pipeline 架构的上下文处理能力。

Usage:
    from myrm_agent_harness.agent.context_management.pipeline import (
        ContextPipeline,
        ProcessorContext,
        create_default_pipeline)

    # 创建默认管道
    pipeline = create_default_pipeline()

    # 处理上下文
    context = ProcessorContext(
        messages=messages,
        user_query=user_query,
        llm=llm)
    result = await pipeline.process(context)
    messages = result.messages
"""

from .base import BaseProcessor, ProcessorContext
from .engine import ContextPipeline, build_default_processors, create_default_pipeline
from .processors import (
    CompressProcessor,
    ExplicitCacheProcessor,
    FilterProcessor,
    SessionNotesProcessor,
    SummarizeProcessor,
    ThinkingBlockCleaner,
)

__all__ = [
    "BaseProcessor",
    "CompressProcessor",
    # 核心类
    "ContextPipeline",
    "ExplicitCacheProcessor",
    "FilterProcessor",
    "ProcessorContext",
    "SessionNotesProcessor",
    "SummarizeProcessor",
    # 处理器
    "ThinkingBlockCleaner",
    "build_default_processors",
    # 工厂函数
    "create_default_pipeline",
]
