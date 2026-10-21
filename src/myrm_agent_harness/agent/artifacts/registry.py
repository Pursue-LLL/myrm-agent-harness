"""工件注册表

使用 ArtifactContext 在 Agent 执行过程中收集生成的工件（文件）。
在 Agent 运行结束时，统一发送 artifacts 事件。
支持实时内容推送（用于前端实时预览）和内联 artifact 即时推送（用于工具生成的媒体资源）。

[INPUT]
- (none)

[OUTPUT]
- GeneratedFile: class — Generated File
- ArtifactRegistry: class — Artifact Registry
- RealtimeContentEvent: class — Realtime Content Event
- RealtimeContentQueue: class — Realtime Content Queue
- InlineArtifactEvent: class — Inline Artifact Event

[POS]
Provides GeneratedFile, ArtifactRegistry, RealtimeContentEvent.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .constants import ArtifactType
from .filters import should_filter_skill_resource, should_ignore_artifact

logger = logging.getLogger(__name__)


@dataclass
class GeneratedFile:
    """生成的文件信息"""

    path: str  # 文件路径（相对于工作空间或容器内路径）
    container_id: str | None = None  # 容器 ID（由 control-plane 注入）


def _should_ignore_file(file_path: str) -> bool:
    """检查文件是否应该被忽略

    过滤规则：
    1. 系统/临时文件（如 .DS_Store, *.pyc）
    2. 技能资源文件（.claude/skills/ 目录下的所有文件）

    Args:
        file_path: 文件路径

    Returns:
        True 如果应该被忽略
    """
    # 1. 检查文件名模式（系统/临时文件）
    filename = Path(file_path).name
    if should_ignore_artifact(filename):
        return True

    # 2. 检查是否为技能资源文件
    return bool(should_filter_skill_resource(file_path))


@dataclass
class ArtifactRegistry:
    """工件注册表

    收集 Agent 执行过程中生成的所有文件。

    设计原则：
    - 框架层只追踪文件路径，不关心业务层概念（user_id/chat_id）
    - 业务层在 process_artifacts_ready 时自行关联用户/会话
    """

    files: list[GeneratedFile] = field(default_factory=list)

    def add_files(self, generated_files: list[str], container_id: str | None = None) -> None:
        """添加生成的文件（自动去重，自动过滤元数据文件）

        Args:
            generated_files: 生成的文件路径列表
            container_id: 容器 ID
        """
        # 获取已注册的文件路径集合用于去重
        existing_paths = {f.path for f in self.files}
        added_count = 0
        ignored_count = 0

        for file_path in generated_files:
            # 过滤元数据和系统文件
            if _should_ignore_file(file_path):
                ignored_count += 1
                continue

            if file_path not in existing_paths:
                self.files.append(GeneratedFile(path=file_path, container_id=container_id))
                existing_paths.add(file_path)
                added_count += 1

        if added_count > 0:
            logger.info(f" 注册 {added_count} 个工件文件（去重后）")
        if ignored_count > 0:
            logger.debug(f" 忽略 {ignored_count} 个元数据/系统文件")

    def get_all_files(self) -> list[GeneratedFile]:
        """获取所有生成的文件"""
        return self.files.copy()

    def __len__(self) -> int:
        """返回已注册文件数量"""
        return len(self.files)

    def clear(self) -> None:
        """清空注册表"""
        self.files.clear()


def get_artifact_registry() -> ArtifactRegistry | None:
    """获取当前的工件注册表

    从统一的 ArtifactContext 获取。

    Returns:
        工件注册表，如果未初始化则返回 None
    """
    from .context import get_artifact_context

    ctx = get_artifact_context()
    if ctx is not None:
        return ctx.artifact_registry
    return None


def register_generated_files(generated_files: list[str], container_id: str | None = None) -> None:
    """注册生成的文件

    工具执行后调用，将生成的文件添加到注册表。

    Args:
        generated_files: 生成的文件路径列表
        container_id: 容器 ID
    """
    from .context import get_artifact_context

    ctx = get_artifact_context()
    if ctx is None:
        logger.debug("ArtifactContext 未初始化，跳过注册")
        return

    ctx.artifact_registry.add_files(generated_files, container_id)


# ========== 实时内容推送支持 ==========


@dataclass
class RealtimeContentEvent:
    """实时内容更新事件"""

    artifact_id: str  # 临时 artifact ID（文件名或路径的哈希）
    filename: str
    content: str  # 完整内容或增量内容
    is_complete: bool  # 是否是完整内容（false 表示增量）
    artifact_type: ArtifactType = ArtifactType.CODE
    language: str | None = None


@dataclass
class RealtimeContentQueue:
    """实时内容事件队列

    用于收集工具执行过程中产生的实时内容更新事件。
    """

    events: list[RealtimeContentEvent] = field(default_factory=list)
    message_id: str | None = None

    def push_content(
        self,
        artifact_id: str,
        filename: str,
        content: str,
        is_complete: bool = True,
        artifact_type: ArtifactType = ArtifactType.CODE,
        language: str | None = None,
    ) -> None:
        """推送内容更新事件"""
        self.events.append(
            RealtimeContentEvent(
                artifact_id=artifact_id,
                filename=filename,
                content=content,
                is_complete=is_complete,
                artifact_type=artifact_type,
                language=language,
            )
        )
        logger.debug(f" 推送实时内容: {filename} (complete={is_complete})")

    def pop_events(self) -> list[RealtimeContentEvent]:
        """获取并清空所有待发送事件"""
        events = self.events.copy()
        self.events.clear()
        return events

    def has_pending_events(self) -> bool:
        """是否有待发送的事件"""
        return len(self.events) > 0


def get_realtime_content_queue() -> RealtimeContentQueue | None:
    """获取当前的实时内容队列

    从统一的 ArtifactContext 获取。

    Returns:
        实时内容队列，如果未初始化则返回 None
    """
    from .context import get_artifact_context

    ctx = get_artifact_context()
    if ctx is not None:
        return ctx.realtime_content_queue
    return None


def push_realtime_content(
    filename: str,
    content: str,
    is_complete: bool = True,
    artifact_type: ArtifactType = ArtifactType.CODE,
    language: str | None = None,
) -> None:
    """推送实时内容更新

    在工具创建/修改文件时调用，用于实时预览。

    Args:
        filename: 文件名
        content: 文件内容
        is_complete: 是否是完整内容
        artifact_type: 工件类型
        language: 编程语言
    """
    import hashlib

    from .context import get_artifact_context

    ctx = get_artifact_context()
    if ctx is None:
        logger.debug("ArtifactContext 未初始化，跳过推送")
        return

    # 使用文件名生成临时 artifact ID
    artifact_id = f"temp_{hashlib.md5(filename.encode()).hexdigest()[:8]}"

    ctx.realtime_content_queue.push_content(
        artifact_id=artifact_id,
        filename=filename,
        content=content,
        is_complete=is_complete,
        artifact_type=artifact_type,
        language=language,
    )


# ========== 内联 Artifact 即时推送 ==========


@dataclass
class InlineArtifactEvent:
    """工具执行过程中产生的内联 artifact（如图片 URL）。

    与 ArtifactRegistry 的区别：ArtifactRegistry 收集沙箱内文件路径，
    需业务层 read_content 持久化；InlineArtifactEvent 携带完整的
    preview_url，可直接发送给前端。
    """

    artifact_id: str
    filename: str
    artifact_type: ArtifactType
    content_type: str
    preview_url: str


@dataclass
class InlineArtifactQueue:
    """内联 artifact 事件队列。

    工具在执行过程中可即时推送 artifact 元数据，
    event pipeline 在每次 updates chunk 后收集并发送 ARTIFACTS 事件。
    """

    events: list[InlineArtifactEvent] = field(default_factory=list)

    def push(self, event: InlineArtifactEvent) -> None:
        self.events.append(event)

    def pop_events(self) -> list[InlineArtifactEvent]:
        events = self.events.copy()
        self.events.clear()
        return events

    def has_pending_events(self) -> bool:
        return len(self.events) > 0


def get_inline_artifact_queue() -> InlineArtifactQueue | None:
    from .context import get_artifact_context

    ctx = get_artifact_context()
    if ctx is not None:
        return ctx.inline_artifact_queue
    return None


def push_inline_artifact(
    *,
    filename: str,
    preview_url: str,
    artifact_type: ArtifactType = ArtifactType.IMAGE,
    content_type: str = "image/png",
) -> None:
    """Push an inline artifact for immediate SSE delivery.

    Call this from tools (e.g. image generation) after producing
    a URL that should be shown to the user immediately.
    """
    import hashlib

    from .context import get_artifact_context

    ctx = get_artifact_context()
    if ctx is None:
        logger.debug("ArtifactContext not initialised, skipping inline artifact push")
        return

    artifact_id = f"inline_{hashlib.md5(preview_url.encode()).hexdigest()[:8]}"
    ctx.inline_artifact_queue.push(
        InlineArtifactEvent(
            artifact_id=artifact_id,
            filename=filename,
            artifact_type=artifact_type,
            content_type=content_type,
            preview_url=preview_url,
        )
    )
    logger.info(" Inline artifact queued: %s", filename)
