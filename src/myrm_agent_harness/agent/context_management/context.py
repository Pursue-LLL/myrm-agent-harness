"""Agent 运行时上下文定义

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- dataclasses::dataclass, field (POS: Python 标准库数据类装饰器)
- typing::TYPE_CHECKING (POS: Python 类型检查标志)

[OUTPUT]
- AgentContext: Agent 运行时上下文数据类

[POS]
Agent runtime context definition. Provides a type-safe context container for passing user, session, and query information during Agent execution. Used by Agent, middlewares, and tools. Supports context isolation and workspace management.

"""

from collections.abc import Mapping
from dataclasses import dataclass

from langchain_core.runnables import RunnableConfig


def _coerce_optional_int(value: object) -> int | None:
    """Convert simple scalar context values to int."""
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return int(value)
    return None


@dataclass
class AgentContext:
    """Agent 运行时上下文

    用于在 Agent 执行过程中传递信息给中间件和工具。

    Attributes:
        user_id: 用户 ID,用于工作空间隔离
        chat_id: 会话 ID,用于工作空间复用
        user_query: 用户原始查询,用于任务感知的过滤
        user_instructions: 用户自定义指令
        max_context_tokens: 模型上下文窗口大小,用于动态计算压缩/摘要阈值
    """

    user_id: str | None = None
    chat_id: str | None = None
    user_query: str = ""
    user_instructions: str | None = None
    max_context_tokens: int | None = None
    last_message_db_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        """转换为字典,用于传递给 agent.run()

        Returns:
            包含所有非 None 字段的字典
        """
        result: dict[str, object] = {}
        if self.user_id is not None:
            result["user_id"] = self.user_id
        if self.chat_id is not None:
            result["chat_id"] = self.chat_id
        if self.user_query:
            result["user_query"] = self.user_query
        if self.user_instructions is not None:
            result["user_instructions"] = self.user_instructions
        if self.max_context_tokens is not None:
            result["max_context_tokens"] = self.max_context_tokens
        if self.last_message_db_id is not None:
            result["last_message_db_id"] = self.last_message_db_id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AgentContext":
        """从字典创建 AgentContext

        Args:
            data: 包含上下文信息的字典

        Returns:
            AgentContext 实例
        """
        max_context_tokens = _coerce_optional_int(data.get("max_context_tokens"))

        return cls(
            user_id=str(data["user_id"]) if data.get("user_id") else None,
            chat_id=str(data["chat_id"]) if data.get("chat_id") else None,
            user_query=str(data.get("user_query", "")),
            user_instructions=str(data["user_instructions"]) if data.get("user_instructions") else None,
            max_context_tokens=max_context_tokens,
            last_message_db_id=str(data["last_message_db_id"]) if data.get("last_message_db_id") else None,
        )


def extract_context_from_request(request: object) -> tuple[str | None, int | None]:
    """从 ModelRequest 中提取上下文信息

    用于中间件从 request.runtime.context 中提取常用字段,消除重复代码。

    Args:
        request: LangChain ModelRequest 对象

    Returns:
        (chat_id, max_context_tokens) tuple
    """
    chat_id: str | None = None
    max_context_tokens: int | None = None

    if hasattr(request, "runtime") and request.runtime:
        context = getattr(request.runtime, "context", None)
        if context:
            if isinstance(context, Mapping):
                raw_chat_id = context.get("chat_id")
                chat_id = str(raw_chat_id) if raw_chat_id is not None else None
                raw_tokens = context.get("max_context_tokens")
                max_context_tokens = _coerce_optional_int(raw_tokens)
            else:
                raw_chat_id = getattr(context, "chat_id", None)
                chat_id = str(raw_chat_id) if raw_chat_id is not None else None
                raw_tokens = getattr(context, "max_context_tokens", None)
                max_context_tokens = _coerce_optional_int(raw_tokens)

    return chat_id, max_context_tokens


def extract_context_from_runnable_config(config: RunnableConfig | None) -> dict[str, object]:
    """Extract normalized runtime context from a tool RunnableConfig."""
    if config is None:
        return {}

    configurable = config.get("configurable")
    if not isinstance(configurable, Mapping):
        return {}

    context = configurable.get("context")
    if not isinstance(context, Mapping):
        return {}

    return dict(context)


__all__ = [
    "AgentContext",
    "extract_context_from_request",
    "extract_context_from_runnable_config",
]
