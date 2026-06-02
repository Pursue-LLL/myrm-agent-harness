"""Artifact Trail 独立跟踪器

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- dataclasses::dataclass, field (POS: Python 数据类装饰器)
- datetime::datetime (POS: Python 日期时间)
- enum::Enum (POS: Python 枚举)
- threading::Lock (POS: Python 线程锁)

[OUTPUT]
- ArtifactAction: Artifact 操作类型枚举
- ArtifactRecord: Artifact 记录数据类
- ArtifactTracker: Artifact 追踪器类
- get_artifact_tracker: 获取追踪器单例的函数

[POS]
Artifact trail tracker. Tracks files created, modified, and deleted by the Agent during a session, solving artifact tracking loss after context compression. Runs silently in the background and injects an index during summarization.

"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Lock


class ArtifactAction(Enum):
    """Artifact 操作类型"""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    READ = "read" # Record read operations for files the Agent accessed


@dataclass
class ArtifactRecord:
    """单个 Artifact 记录

    Attributes:
        path: 文件路径(工作空间相对路径或绝对路径)
        action: 操作类型
        timestamp: 操作时间
        round_number: 对话轮次(如果可追踪)
        description: 操作描述(可选)
        tool_name: 触发操作的工具名称
    """

    path: str
    action: ArtifactAction
    timestamp: datetime = field(default_factory=datetime.now)
    round_number: int | None = None
    description: str = ""
    tool_name: str = ""


@dataclass
class ArtifactTracker:
    """Artifact 追踪器

    按 chat_id 维护,追踪会话中所有文件操作。

    线程安全:所有修改操作都加锁保护。
    """

    chat_id: str
    created_at: datetime = field(default_factory=datetime.now)
    _records: list[ArtifactRecord] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record(
        self,
        path: str,
        action: ArtifactAction,
        tool_name: str = "",
        description: str = "",
        round_number: int | None = None,
    ) -> None:
        """记录一次文件操作

        Args:
            path: 文件路径
            action: 操作类型
            tool_name: 触发操作的工具名称
            description: 操作描述
            round_number: 对话轮次
        """
        record = ArtifactRecord(
            path=path, action=action, tool_name=tool_name, description=description, round_number=round_number
        )
        with self._lock:
            self._records.append(record)

    def record_creation(self, path: str, tool_name: str = "", description: str = "") -> None:
        """记录文件创建"""
        self.record(path, ArtifactAction.CREATED, tool_name, description)

    def record_modification(self, path: str, tool_name: str = "", description: str = "") -> None:
        """记录文件修改"""
        self.record(path, ArtifactAction.MODIFIED, tool_name, description)

    def record_deletion(self, path: str, tool_name: str = "", description: str = "") -> None:
        """记录文件删除"""
        self.record(path, ArtifactAction.DELETED, tool_name, description)

    @property
    def records(self) -> list[ArtifactRecord]:
        """获取所有记录(只读副本)"""
        with self._lock:
            return list(self._records)

    @property
    def created_files(self) -> list[str]:
        """获取所有创建的文件路径(去重)"""
        with self._lock:
            return list({r.path for r in self._records if r.action == ArtifactAction.CREATED})

    @property
    def modified_files(self) -> list[str]:
        """获取所有修改的文件路径(去重)"""
        with self._lock:
            return list({r.path for r in self._records if r.action == ArtifactAction.MODIFIED})

    @property
    def deleted_files(self) -> list[str]:
        """获取所有删除的文件路径(去重)"""
        with self._lock:
            return list({r.path for r in self._records if r.action == ArtifactAction.DELETED})

    def get_summary(self, max_items: int = 20) -> str:
        """生成 artifact 索引摘要

        用于注入到摘要消息中。

        优化逻辑:如果文件曾被创建,即使后来被修改,也显示为"创建"。
        因为从用户视角,这是会话中"新产生"的文件。

        Args:
            max_items: 最大显示条目数

        Returns:
            格式化的 artifact 索引字符串
        """
        with self._lock:
            if not self._records:
                return ""

            # Collect path operations and detect whether the path was created
            path_created: set[str] = set()
            path_latest: dict[str, ArtifactRecord] = {}

            for record in self._records:
                if record.action == ArtifactAction.CREATED:
                    path_created.add(record.path)
                path_latest[record.path] = record

            records = sorted(path_latest.values(), key=lambda r: r.timestamp, reverse=True)

            # Classify paths created during this session as created
            created: list[str] = []
            modified: list[str] = []
            deleted: list[str] = []

            for r in records[:max_items]:
                entry = f" - {r.path}"
                if r.description:
                    entry += f" ({r.description})"

                # A path created during this session remains classified as created
                if r.path in path_created and r.action != ArtifactAction.DELETED:
                    created.append(entry)
                elif r.action == ArtifactAction.MODIFIED:
                    modified.append(entry)
                elif r.action == ArtifactAction.DELETED:
                    deleted.append(entry)

            parts: list[str] = []
            if created:
                parts.append("创建的文件:")
                parts.extend(created)
            if modified:
                if parts:
                    parts.append("")
                parts.append("修改的文件:")
                parts.extend(modified)
            if deleted:
                if parts:
                    parts.append("")
                parts.append("删除的文件:")
                parts.extend(deleted)

            if len(records) > max_items:
                parts.append(f"\n... 共 {len(records)} 个文件操作,仅显示最近 {max_items} 个")

            return "\n".join(parts)

    def clear(self) -> None:
        """清空所有记录"""
        with self._lock:
            self._records.clear()


# ============ 全局存储 ============

# 存储所有 chat_id 的 ArtifactTracker
_tracker_store: dict[str, ArtifactTracker] = {}
_store_lock = Lock()

# 内存管理配置
DEFAULT_TRACKER_TTL_SECONDS: int = 24 * 60 * 60  # 24 小时
MAX_TRACKER_ENTRIES: int = 500  # 最大追踪器数量


def _cleanup_expired_trackers_unsafe() -> int:
    """清理过期的追踪器(不加锁版本,由调用方确保锁定)

    Returns:
        清理的追踪器数量
    """
    now = datetime.now()
    expired_ids = [
        chat_id
        for chat_id, tracker in _tracker_store.items()
        if (now - tracker.created_at).total_seconds() > DEFAULT_TRACKER_TTL_SECONDS
    ]

    for chat_id in expired_ids:
        del _tracker_store[chat_id]

    return len(expired_ids)


def create_artifact_tracker(chat_id: str) -> ArtifactTracker:
    """创建或获取指定会话的 ArtifactTracker

    Args:
        chat_id: 会话 ID

    Returns:
        ArtifactTracker 实例
    """
    with _store_lock:
        # 检查是否已存在
        if chat_id in _tracker_store:
            return _tracker_store[chat_id]

        # Memory guard: clean up when needed
        if len(_tracker_store) >= MAX_TRACKER_ENTRIES:
            cleaned = _cleanup_expired_trackers_unsafe()
            if cleaned == 0 and len(_tracker_store) >= MAX_TRACKER_ENTRIES:
                # Remove the oldest 10% when no entries are expired
                oldest = sorted(_tracker_store.items(), key=lambda x: x[1].created_at)
                for cid, _ in oldest[: MAX_TRACKER_ENTRIES // 10]:
                    del _tracker_store[cid]

        # 创建新的追踪器
        tracker = ArtifactTracker(chat_id=chat_id)
        _tracker_store[chat_id] = tracker
        return tracker


def get_artifact_tracker(chat_id: str) -> ArtifactTracker | None:
    """获取指定会话的 ArtifactTracker

    Args:
        chat_id: 会话 ID

    Returns:
        ArtifactTracker 实例,不存在返回 None
    """
    with _store_lock:
        return _tracker_store.get(chat_id)


def get_or_create_artifact_tracker(chat_id: str) -> ArtifactTracker:
    """获取或创建指定会话的 ArtifactTracker

    Args:
        chat_id: 会话 ID

    Returns:
        ArtifactTracker 实例
    """
    return create_artifact_tracker(chat_id)


def clear_artifact_tracker(chat_id: str) -> bool:
    """清除指定会话的 ArtifactTracker

    Args:
        chat_id: 会话 ID

    Returns:
        是否成功清除
    """
    with _store_lock:
        if chat_id in _tracker_store:
            del _tracker_store[chat_id]
            return True
        return False


def get_all_active_trackers() -> dict[str, ArtifactTracker]:
    """获取所有活跃的追踪器(只读副本)"""
    with _store_lock:
        return dict(_tracker_store)
