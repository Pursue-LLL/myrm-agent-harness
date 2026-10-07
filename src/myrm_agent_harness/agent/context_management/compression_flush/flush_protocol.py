"""上下文压缩前置强制内存落盘协议与门禁实现。

在滑动窗口丢弃或 LLM 摘要压缩执行前，强制执行未持久化记忆的落盘写入，
从物理上杜绝长会话压缩导致的不可逆失忆。

[INPUT]
- agent.context_management.compression_flush.types::FlushItem, FlushResult, FlushTriggerReason (POS:
  多智能体与长会话上下文压缩即时持久化刷盘协议核心类型。)

[OUTPUT]
- PreCompressionMemoryFlushHook: 上下文压缩前置内存强制刷盘门禁控制器。

[POS]
上下文压缩前置强制内存落盘协议与门禁实现。
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from myrm_agent_harness.agent.context_management.compression_flush.types import (
    FlushItem,
    FlushResult,
    FlushTriggerReason,
)


class PreCompressionMemoryFlushHook:
    """上下文压缩前置内存强制刷盘门禁控制器。"""

    def __init__(
        self,
        persistence_handler: (
            Callable[[str, list[FlushItem]], bool] | None
        ) = None,
    ) -> None:
        self._lock = threading.Lock()
        self._persistence_handler = persistence_handler
        # session_id -> list of pending FlushItems
        self._pending_buffer: dict[str, list[FlushItem]] = {}
        # session_id -> list of persisted FlushItems (本地常驻已落盘归档)
        self._flushed_archive: dict[str, list[FlushItem]] = {}

    def register_persistence_handler(
        self, handler: Callable[[str, list[FlushItem]], bool]
    ) -> None:
        """注册外部底层持久化存储的回调函数 (如 SQLite / VectorStore)。"""
        with self._lock:
            self._persistence_handler = handler

    def register_pending_item(self, session_id: str, item: FlushItem) -> None:
        """注册待落盘的临时易变记忆或决策约束。"""
        with self._lock:
            if session_id not in self._pending_buffer:
                self._pending_buffer[session_id] = []
            self._pending_buffer[session_id].append(item)

    def register_pending_items(
        self, session_id: str, items: list[FlushItem]
    ) -> None:
        """批量注册待落盘项。"""
        with self._lock:
            if session_id not in self._pending_buffer:
                self._pending_buffer[session_id] = []
            self._pending_buffer[session_id].extend(items)

    def get_pending_count(self, session_id: str) -> int:
        """获取指定会话当前暂存未落盘的项目数量。"""
        with self._lock:
            return len(self._pending_buffer.get(session_id, []))

    def get_pending_items(self, session_id: str) -> list[FlushItem]:
        """获取指定会话当前待落盘项目快照列表。"""
        with self._lock:
            return list(self._pending_buffer.get(session_id, []))

    def get_flushed_archive(self, session_id: str) -> list[FlushItem]:
        """获取指定会话已经成功落盘的历史归档。"""
        with self._lock:
            return list(self._flushed_archive.get(session_id, []))

    def execute_pre_compression_flush(
        self,
        session_id: str,
        reason: FlushTriggerReason = FlushTriggerReason.COMPRESSION,
    ) -> FlushResult:
        """执行压缩前置强制落盘。

        若存在待落盘项，原子调用持久化处理器落盘；成功后从缓冲区清空并沉淀至归档。
        若持久化失败，不清理缓冲区以防数据丢失。
        """
        with self._lock:
            pending = self._pending_buffer.get(session_id, [])
            if not pending:
                return FlushResult(
                    session_id=session_id,
                    reason=reason,
                    is_success=True,
                    flushed_items_count=0,
                    flushed_categories=[],
                )

            categories = sorted({item.category for item in pending})
            items_to_flush = list(pending)

            # 调用外部持久化回调
            if self._persistence_handler is not None:
                try:
                    success = self._persistence_handler(
                        session_id, items_to_flush
                    )
                except Exception as exc:
                    return FlushResult(
                        session_id=session_id,
                        reason=reason,
                        is_success=False,
                        flushed_items_count=0,
                        flushed_categories=categories,
                        error_message=f"Persistence handler exception: {exc}",
                    )

                if not success:
                    return FlushResult(
                        session_id=session_id,
                        reason=reason,
                        is_success=False,
                        flushed_items_count=0,
                        flushed_categories=categories,
                        error_message="Persistence handler returned failure status",
                    )

            # 持久化成功：转移至归档并清空待处理缓冲
            if session_id not in self._flushed_archive:
                self._flushed_archive[session_id] = []
            self._flushed_archive[session_id].extend(items_to_flush)
            self._pending_buffer[session_id].clear()

            return FlushResult(
                session_id=session_id,
                reason=reason,
                is_success=True,
                flushed_items_count=len(items_to_flush),
                flushed_categories=categories,
            )

    def clear_session(self, session_id: str) -> None:
        """清理会话的所有缓冲与归档状态。"""
        with self._lock:
            self._pending_buffer.pop(session_id, None)
            self._flushed_archive.pop(session_id, None)
