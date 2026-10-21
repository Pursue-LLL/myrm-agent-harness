"""Pipeline 处理器基类

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- abc::ABC, abstractmethod (POS: Python 抽象基类)
- dataclasses::dataclass, field (POS: Python 数据类装饰器)
- langchain_core.messages::BaseMessage (POS: LangChain 消息基类)
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM 基类)
- infra.schemas::StructuredSummary (POS: 结构化摘要数据类)

[OUTPUT]
- ProcessorContext: 处理器上下文数据类(在 Pipeline 中传递,含摘要输出字段)
- BaseProcessor: 处理器抽象基类(定义 process 接口)

[POS]
Pipeline processor base class. Defines the processor interface (BaseProcessor) and context data structure (ProcessorContext) for the chain-of-responsibility execution model.

"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

if TYPE_CHECKING:
    from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary


@dataclass
class ProcessorContext:
    """处理器上下文

    在 Pipeline 中传递的数据结构,包含消息列表和元信息。
        压缩/缓存剪枝阶段可由业务层注入落盘回调(ContextCompressOffloadCallback),
    大输出(≥5k tokens)写入 .context/{chat_id}/ 目录,符合 Manus "有损但可追溯"原则。

    Attributes:
        messages: 消息列表(会被处理器修改)
        user_query: 用户查询(任务上下文)
        user_id: 用户 ID
        chat_id: 会话 ID
        llm: LLM 客户端(用于需要 LLM 的处理器)
        summarizer_llm: Lite/auxiliary LLM for archive summaries (falls back to llm when unset)
        is_resume: Resume 状态标志(从 interrupt() 恢复时为 True)
        merged_context: Agent merged context(用于访问 hitl_session_active 等标记)
        tokens_saved: 累计节省的 token 数
        operations: 已执行的操作列表
        metadata: 处理器间共享的元数据(如压缩边界、模型信息等)
        structured_summary: SummarizeProcessor 产生的摘要(供 Middleware 持久化)
        last_summarized_message_id: 摘要覆盖的最后一条消息的 DB ID
    """

    messages: list[BaseMessage]
    user_query: str
    user_id: str | None = None
    chat_id: str | None = None
    llm: BaseChatModel | None = None
    summarizer_llm: BaseChatModel | None = None

    # Prompt Cache preservation flags
    is_resume: bool = False
    merged_context: dict[str, object] = field(default_factory=dict)

    # 统计信息
    tokens_saved: int = 0
    operations: list[str] = field(default_factory=list)

    # 处理器间共享的元数据
    metadata: dict[str, object] = field(default_factory=dict)

    # SummarizeProcessor 输出(供 Middleware 桥接到业务层持久化)
    structured_summary: "StructuredSummary | None" = None
    last_summarized_message_id: str | None = None


class BaseProcessor(ABC):
    """处理器基类

    每个处理器只负责一个特定的上下文转换任务。
    遵循单一职责原则,便于测试和扩展。

    子类需要实现:
    - name: 处理器名称(用于日志和调试)
    - should_process: 判断是否需要处理
    - process: 执行处理逻辑
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """处理器名称"""
        pass

    def _should_skip_for_cache_preservation(self, context: ProcessorContext) -> bool:
        """Prompt Cache preservation check

        修改性Processor(Filter/Compress/SessionNotes/Summarize)必须在以下情况跳过:
        1. Resume 时(从 interrupt() 恢复):保持历史messages不变
        2. HITL会话期间:避免多次HITL交互时破坏cache

        符合Manus"只追加,不删除历史"最佳实践。

        Args:
            context: 处理器上下文

        Returns:
            是否应该跳过(True = 跳过,保护Cache)
        """
        if context.is_resume:
            return True

        return bool(context.merged_context.get("hitl_session_active"))

    @abstractmethod
    async def should_process(self, context: ProcessorContext) -> bool:
        """判断是否需要处理

        Args:
            context: 处理器上下文

        Returns:
            是否需要处理
        """
        pass

    @abstractmethod
    async def process(self, context: ProcessorContext) -> ProcessorContext:
        """执行处理

        Args:
            context: 处理器上下文

        Returns:
            处理后的上下文(通常是原地修改)
        """
        pass
