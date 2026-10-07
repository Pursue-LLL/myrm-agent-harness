# [POS] myrm_agent_harness/agent/context_management/compression_flush/types.py
# [INPUT] None (纯领域类型与数据模型定义)
# [OUTPUT] FlushTriggerReason, FlushItem, FlushResult, MemoryIsolationScope, EphemeralMemoryOverlaySpec, SubagentMemoryPolicy, StatelessCronSpec

"""多智能体与长会话上下文压缩即时持久化刷盘协议核心类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class FlushTriggerReason(StrEnum):
    """触发前置内存落盘的原因枚举。"""

    COMPRESSION = "compression"  # 上下文达到阈值触发滑动窗口或摘要压缩
    SUBAGENT_SPAWN = "subagent_spawn"  # 派生子智能体前保存父级完整状态
    SESSION_CLOSING = "session_closing"  # 会话正常结束或挂起
    MANUAL = "manual"  # 外部或测试手动触发


class MemoryIsolationScope(StrEnum):
    """内存隔离沙箱级别。"""

    STATELESS_CRON = "stateless_cron"  # 定时任务无状态隔离 (强制自包含，剥离易变画像)
    SUBAGENT_OVERLAY = "subagent_overlay"  # 子智能体临时覆盖卷 (父级只读 + 过程临时写入)
    FULL_PARENT_READONLY = "full_parent_readonly"  # 完全父级只读，禁止任何写入
    ROOT_SESSION = "root_session"  # 根会话，拥有完全持久化写入权限


@dataclass(frozen=True)
class FlushItem:
    """待落盘的临时易变记忆或原子决策项。"""

    item_id: str
    category: str  # e.g., "user_preference", "architectural_constraint", "code_convention"
    content: str
    source_turn: int = 0
    importance_score: float = 1.0
    tags: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class FlushResult:
    """前置内存落盘执行结果。"""

    session_id: str
    reason: FlushTriggerReason
    is_success: bool
    flushed_items_count: int
    flushed_categories: list[str]
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    error_message: str = ""


@dataclass(frozen=True)
class EphemeralMemoryOverlaySpec:
    """子智能体临时内存覆盖卷规格。"""

    overlay_id: str
    parent_session_id: str
    allow_selective_merge: bool = True
    auto_purge_on_finish: bool = True
    max_overlay_items: int = 50


@dataclass(frozen=True)
class SubagentMemoryPolicy:
    """子智能体内存沙箱安全策略。"""

    isolation_scope: MemoryIsolationScope = MemoryIsolationScope.SUBAGENT_OVERLAY
    allow_profile_read: bool = True
    allow_ephemeral_write: bool = True
    auto_purge: bool = True


@dataclass(frozen=True)
class StatelessCronSpec:
    """定时任务无状态执行规格。"""

    task_id: str
    task_name: str
    strip_user_profile: bool = True
    require_self_contained: bool = True
