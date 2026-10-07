"""内外双层循环实时代令引导、键盘意图分流与排队队列套件强类型契约定义。

[INPUT]
- 无外部动态依赖，定义双循环指令类别枚举、键盘手势意图枚举、代令指令实体与队列大盘契约。

[OUTPUT]
- LoopSteeringKind: 循环代令类别枚举 (INNER_LOOP_STEER, OUTER_LOOP_FOLLOW_UP)
- KeyStrokeIntent: 键盘手势意图枚举 (ENTER_LIVE_STEER, ALT_ENTER_ENQUEUE, ALT_UP_RECALL_EDIT)
- SteeringDirectiveStatus: 指令生命周期状态枚举 (PENDING, INJECTED, EXECUTED, RECALLED)
- SteeringDirective: 双层循环引导指令契约
- DualLoopQueueSnapshot: 会话双循环排队大盘快照契约

[POS]
- 位于 context_management/dual_loop_steering/dual_loop_steering_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum


class LoopSteeringKind(StrEnum):
    """指令注入目标循环层级枚举。"""

    INNER_LOOP_STEER = "inner_loop_steer"        # 内层循环：工具执行间隙原子注入，下一动作即刻改向
    OUTER_LOOP_FOLLOW_UP = "outer_loop_follow_up"  # 外层循环：主任务收敛完成后顺次执行的后续排队项


class KeyStrokeIntent(StrEnum):
    """输入框人体工学极简键盘交互手势意图枚举。"""

    ENTER_LIVE_STEER = "enter_live_steer"          # Enter: 忙碌中直接当场改向代令
    ALT_ENTER_ENQUEUE = "alt_enter_enqueue"        # Alt/Option+Enter: 优雅折叠入排队队列
    ALT_UP_RECALL_EDIT = "alt_up_recall_edit"      # Alt/Option+↑: 瞬间取回首项排队指令就地编辑


class SteeringDirectiveStatus(StrEnum):
    """指令生命周期状态枚举。"""

    PENDING = "pending"          # 正在队列中等待
    INJECTED = "injected"        # 已原子注入内层活跃上下文
    EXECUTED = "executed"        # 已完成执行
    RECALLED = "recalled"        # 用户已通过 Alt+↑ 取回编辑


@dataclass(frozen=True)
class SteeringDirective:
    """双层循环引导代令指令实体契约。"""

    directive_id: str
    session_id: str
    kind: LoopSteeringKind
    prompt_text: str
    status: SteeringDirectiveStatus
    priority: int = 0
    enqueued_at_iso: str = ""
    injected_at_iso: str | None = None


@dataclass(frozen=True)
class DualLoopQueueSnapshot:
    """会话级双层循环排队大盘快照契约。"""

    session_id: str
    pending_inner_steer_count: int
    pending_outer_follow_up_count: int
    inner_queue: tuple[SteeringDirective, ...]
    outer_queue: tuple[SteeringDirective, ...]
    is_busy_navigating: bool
    snapshot_at_iso: str
