"""双轨冻结快照记忆预算仪表盘、原子批量腾挪策展操作符与长程会话回溯锚点核心类型。

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- MemoryOperationType: 原子记忆批量操作类型。
- MemoryBatchOperation: 原子批量事务中的单项操作符。
- MemoryBudgetSpec: 声明式记忆上下文预算规约。
- MemoryBudgetStatus: 实时记忆字符/Token 与槽位预算状态仪表盘。
- ManagedMemoryItem: 策展中受管辖的单条记忆原子项。
- AtomicBatchResult: 原子批量腾挪事务执行结果。
- ScrollMessageItem: 会话历史穿透翻页中的消息条目。
- ScrollAnchorRequest: 围绕指定消息锚点的双向滑动翻页请求。
- ScrollAnchorResult: 围绕消息锚点的滑动翻页穿透结果。

[POS]
双轨冻结快照记忆预算仪表盘、原子批量腾挪策展操作符与长程会话回溯锚点核心类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MemoryOperationType(StrEnum):
    """原子记忆批量操作类型。"""

    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"


@dataclass(frozen=True)
class MemoryBatchOperation:
    """原子批量事务中的单项操作符。"""

    operation_type: MemoryOperationType
    target_id: str | None = None
    target_substring: str | None = None
    new_id: str | None = None
    new_content: str | None = None
    estimated_tokens: int = 0


@dataclass(frozen=True)
class MemoryBudgetSpec:
    """声明式记忆上下文预算规约。"""

    max_tokens: int = 2500
    max_slots: int = 20
    warning_threshold_pct: float = 80.0  # 预算占用预警百分比


@dataclass(frozen=True)
class MemoryBudgetStatus:
    """实时记忆字符/Token 与槽位预算状态仪表盘。"""

    used_tokens: int
    max_tokens: int
    token_usage_pct: float
    used_slots: int
    max_slots: int
    slot_usage_pct: float
    is_warning: bool
    is_overflow: bool
    budget_header_slice: str


@dataclass(frozen=True)
class ManagedMemoryItem:
    """策展中受管辖的单条记忆原子项。"""

    item_id: str
    content: str
    token_count: int


@dataclass(frozen=True)
class AtomicBatchResult:
    """原子批量腾挪事务执行结果。"""

    is_success: bool
    applied_count: int
    rolled_back: bool
    error_message: str
    current_budget: MemoryBudgetStatus
    retained_items: list[ManagedMemoryItem] = field(default_factory=list)


@dataclass(frozen=True)
class ScrollMessageItem:
    """会话历史穿透翻页中的消息条目。"""

    message_id: str
    role: str
    content: str
    created_at: str


@dataclass(frozen=True)
class ScrollAnchorRequest:
    """围绕指定消息锚点的双向滑动翻页请求。"""

    conversation_id: str
    around_message_id: str
    before_limit: int = 5
    after_limit: int = 5


@dataclass(frozen=True)
class ScrollAnchorResult:
    """围绕消息锚点的滑动翻页穿透结果。"""

    conversation_id: str
    around_message_id: str
    messages: list[ScrollMessageItem]
    has_more_before: bool
    has_more_after: bool
