"""并发状态变异隔离与安全事件管道类型定义模块.

本模块定义会话状态并发变异写隔离、无锁冲突防护与受控事件管道生命周期所需的所有核心数据模型与枚举类型。
严禁使用 Any 类型，确保完全强类型化。

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- ChannelLifecycleState
- PatchConflictStrategy
- ChannelPutStatus
- PatchConflictError
- StateMutationPatch
- PatchCommitResult
- ChannelPutResult
- SessionStateSnapshot

[POS]
并发状态变异隔离与安全事件管道类型定义模块.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ChannelLifecycleState(StrEnum):
    """事件管道的物理生命周期状态枚举."""

    ACTIVE = "active"  # 正常活跃状态，允许投递与读取
    DRAINING = "draining"  # 排空中状态，拒绝新事件投递，仅允许读取排空存量事件
    CLOSED = "closed"  # 彻底关闭状态，禁止任何读写，资源已清理


class PatchConflictStrategy(StrEnum):
    """状态变异 Patch 冲突仲裁策略."""

    LAST_WRITE_WINS = "last_write_wins"  # 发生版本冲突时后提交者覆盖冲突键
    FAIL_ON_CONFLICT = "fail_on_conflict"  # 发生版本冲突时拒绝合入并抛出冲突异常
    MERGE_DICT = "merge_dict"  # 对嵌套字典进行递归合并，非字典则后写胜出


class ChannelPutStatus(StrEnum):
    """向事件管道投递事件的判决结果枚举."""

    DELIVERED = "delivered"  # 成功入队
    DROPPED_CHANNEL_CLOSED = "dropped_channel_closed"  # 管道已关闭，安全丢弃
    DROPPED_DRAINING = "dropped_draining"  # 管道处于排空阶段，拒绝新事件
    DROPPED_QUEUE_FULL = "dropped_queue_full"  # 管道缓冲区满且超时，安全丢弃以防死锁


class PatchConflictError(Exception):
    """当并发状态变异发生不可调和的版本冲突时抛出的强类型异常."""

    def __init__(self, message: str, conflict_keys: list[str]) -> None:
        super().__init__(message)
        self.conflict_keys: list[str] = conflict_keys


@dataclass(frozen=True)
class StateMutationPatch:
    """并发分支提交的状态原子变异包（Mutation Patch）."""

    patch_id: str
    branch_id: str
    base_version: int
    mutations: dict[str, object]
    timestamp_ms: float = field(default_factory=lambda: time.time() * 1000)


@dataclass(frozen=True)
class PatchCommitResult:
    """变异 Patch 仲裁合入结果."""

    success: bool
    resulting_version: int
    applied_keys: list[str]
    conflicted_keys: list[str] = field(default_factory=list)
    error_message: str | None = None


@dataclass(frozen=True)
class ChannelPutResult:
    """事件投递至安全管道的结果对象."""

    status: ChannelPutStatus
    event_id: str
    dropped_reason: str | None = None


@dataclass(frozen=True)
class SessionStateSnapshot:
    """会话状态不可变快照."""

    session_id: str
    version: int
    data: dict[str, object]
    updated_at_ms: float
