"""辩证推理深度用户表征与自适应会话步调动态节流核心类型。

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- SessionHeatState: 会话冷热活跃状态。
- UserBaseProfile: 长期相对稳定的用户基础画像 (低频刷新，捍卫前缀缓存)。
- DialecticEphemeralMind: 即时认知心智状态与瞬间关切 (放置于 Volatile 层末端，300~500 字符内)。
- DialecticCadenceConfig: 自适应会话步调与节流配置。
- DialecticReasoningResult: 辩证推理与步调调度执行结果。

[POS]
辩证推理深度用户表征与自适应会话步调动态节流核心类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class SessionHeatState(StrEnum):
    """会话冷热活跃状态。"""

    COLD_BOOT = "cold_boot"  # 冷启动阶段 (前 1~2 轮，主要探寻用户角色定位)
    WARM = "warm"  # 升温中
    HOT_ACTIVE = "hot_active"  # 热会话阶段 (深度聚焦当前任务核心约束与隐式抗拒点)


@dataclass(frozen=True)
class UserBaseProfile:
    """长期相对稳定的用户基础画像 (低频刷新，捍卫前缀缓存)。"""

    user_id: str
    primary_role: str = ""  # 用户主要角色 (如 "全栈架构师")
    technical_stack: list[str] = field(default_factory=list)  # 熟练技术栈
    preferred_style: str = ""  # 偏好代码与交互风格 (如 "简洁单一职责，拒绝向后兼容包袱")
    core_constraints: list[str] = field(default_factory=list)  # 长期硬性约束
    last_updated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class DialecticEphemeralMind:
    """即时认知心智状态与瞬间关切 (放置于 Volatile 层末端，300~500 字符内)。"""

    conversation_id: str
    immediate_focus: str  # 当前最核心关注点 (如 "解决 SQLite 锁冲突与内存背压")
    resistance_points: list[str] = field(default_factory=list)  # 用户抗拒点/痛点 (如 "反感引入外部重型守护进程")
    implicit_goals: list[str] = field(default_factory=list)  # 潜意识隐式目标 (如 "极简轻量级，零外部运维依赖")
    confidence: float = 1.0
    turn_index: int = 0
    updated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class DialecticCadenceConfig:
    """自适应会话步调与节流配置。"""

    base_profile_cadence_turns: int = 5  # 基础画像每 5 轮才评估一次低频刷新
    ephemeral_cadence_turns: int = 2  # 即时心智每 2 轮评估一次动态提炼
    cold_boot_threshold_turns: int = 2  # 冷启动判定轮次
    max_ephemeral_chars: int = 500  # 即时关切最大字符限制
    enable_throttling: bool = True  # 是否开启动态步调节流


@dataclass(frozen=True)
class DialecticReasoningResult:
    """辩证推理与步调调度执行结果。"""

    conversation_id: str
    turn_index: int
    is_throttled: bool
    heat_state: SessionHeatState
    base_profile_updated: bool
    ephemeral_mind_updated: bool
    ephemeral_mind: DialecticEphemeralMind | None = None
    prompt_volatile_slice: str = ""
    reasoning_summary: str = ""
