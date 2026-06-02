"""工件上下文管理器

统一管理所有工件相关注册表的生命周期。
使用上下文管理器模式确保正确初始化和清理。

设计原则：
- 框架层只追踪文件路径，不关心业务层概念（user_id/chat_id）
- 业务层在 process_artifacts_ready 时自行关联用户/会话

[INPUT]
- (none)

[OUTPUT]
- ArtifactContext: class — Artifact Context
- ArtifactContextManager: Usage:
- get_artifact_context: Returns:

[POS]
Provides ArtifactContext, ArtifactContextManager, get_artifact_context.
"""

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from types import TracebackType

from .file_id_registry import FileIdRegistry
from .registry import ArtifactRegistry, InlineArtifactQueue, RealtimeContentQueue
from .ui_registry import UIRegistry

logger = logging.getLogger(__name__)


@dataclass
class ArtifactContext:
    """工件上下文

    统一管理以下注册表：
    - ArtifactRegistry: 文件工件注册表
    - UIRegistry: UI 工件注册表
    - RealtimeContentQueue: 实时内容推送队列
    - InlineArtifactQueue: 内联 artifact 即时推送队列
    - FileIdRegistry: 文件 ID 短链接注册表
    """

    artifact_registry: ArtifactRegistry = field(default_factory=ArtifactRegistry)
    ui_registry: UIRegistry = field(default_factory=UIRegistry)
    realtime_content_queue: RealtimeContentQueue = field(default_factory=RealtimeContentQueue)
    inline_artifact_queue: InlineArtifactQueue = field(default_factory=InlineArtifactQueue)
    file_id_registry: FileIdRegistry = field(default_factory=FileIdRegistry)

    # 上下文元数据（仅 message_id，无业务层概念）
    message_id: str | None = None


# 全局上下文变量
_artifact_context_var: ContextVar[ArtifactContext | None] = ContextVar("artifact_context", default=None)


class ArtifactContextManager:
    """工件上下文管理器

    使用上下文管理器模式管理所有注册表的生命周期。

    Usage:
        async with ArtifactContextManager(message_id="yyy"):
            # 在此范围内，所有注册表已初始化
            # 可以通过 get_artifact_context() 获取上下文
            ctx = get_artifact_context()
            ctx.artifact_registry.add_files(...)

        # 离开上下文后，所有注册表自动清理
    """

    def __init__(self, message_id: str | None = None) -> None:
        self.message_id = message_id
        self._token: Token[ArtifactContext | None] | None = None
        self._context: ArtifactContext | None = None

    def __enter__(self) -> "ArtifactContext":
        """进入上下文，初始化所有注册表"""
        # 创建上下文对象
        self._context = ArtifactContext(
            artifact_registry=ArtifactRegistry(),
            ui_registry=UIRegistry(),
            realtime_content_queue=RealtimeContentQueue(message_id=self.message_id),
            inline_artifact_queue=InlineArtifactQueue(),
            file_id_registry=FileIdRegistry(),
            message_id=self.message_id,
        )

        # 设置上下文变量
        self._token = _artifact_context_var.set(self._context)

        logger.info(" 工件上下文已初始化")
        return self._context

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """离开上下文，清理所有注册表"""
        if self._token is not None:
            try:
                _artifact_context_var.reset(self._token)
            except ValueError:
                # Token was created in a different async context.
                # This can happen when the async generator is cancelled across context boundaries
                # (e.g., LangGraph's cancel scope switches contexts during cleanup).
                # Safe to ignore as the original context no longer exists.
                logger.warning(" Context variable reset skipped: token created in different context")
            self._token = None

        if self._context is not None:
            self._context = None

        logger.info(" 工件上下文已清理")

    async def __aenter__(self) -> "ArtifactContext":
        """异步进入上下文（与同步版本相同）"""
        return self.__enter__()

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """异步离开上下文（与同步版本相同）"""
        self.__exit__(exc_type, exc_val, exc_tb)


def get_artifact_context() -> ArtifactContext | None:
    """获取当前的工件上下文

    Returns:
        工件上下文，如果未初始化则返回 None
    """
    return _artifact_context_var.get()


__all__ = [
    "ArtifactContext",
    "ArtifactContextManager",
    "get_artifact_context",
]
