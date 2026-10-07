"""强类型契约定义：个人画像与专业偏好全域按需水合与大模型创造力保鲜套件。

[INPUT]
- 无外部动态依赖，定义用户偏好卡片、水合触发决策与创造力保鲜契约。

[OUTPUT]
- ProfileCardCategory: 用户画像与偏好卡片类别枚举
- HydrationTriggerMode: 水合触发模式枚举 (显式快捷指令 / 隐式语义路由 / 创造力保鲜旁路)
- UserMemoryCard: 细粒度个人画像独立记忆卡片契约
- HydrationDecision: 水合策略决策结果契约
- HydratedContextEnvelope: 上下文水合包装体契约
- DemandHydrationConfig: 按需水合与创造力保鲜配置契约

[POS]
- 位于 context_management/demand_hydration/demand_hydration_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence
from langchain_core.messages import BaseMessage


class ProfileCardCategory(StrEnum):
    """用户偏好卡片类别枚举。"""

    CODING_STYLE = "coding_style"
    WRITING_TONE = "writing_tone"
    DOMAIN_GLOSSARY = "domain_glossary"
    ARCHITECTURE_STANDARD = "architecture_standard"
    PERSONAL_BIO = "personal_bio"


class HydrationTriggerMode(StrEnum):
    """水合触发姿态枚举。"""

    EXPLICIT_COMMAND = "explicit_command"
    IMPLICIT_ROUTING = "implicit_routing"
    CREATIVITY_BYPASS = "creativity_bypass"


@dataclass(frozen=True)
class UserMemoryCard:
    """细粒度解耦的个人画像记忆卡片。"""

    card_id: str
    title: str
    category: ProfileCardCategory
    content: str
    token_estimate: int
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HydrationDecision:
    """水合决策结果契约。"""

    should_hydrate: bool
    trigger_mode: HydrationTriggerMode
    hydrated_cards: list[UserMemoryCard]
    reason: str
    creativity_preserved: bool


@dataclass(frozen=True)
class HydratedContextEnvelope:
    """上下文按需水合封装体契约。"""

    original_messages: list[BaseMessage]
    hydrated_messages: list[BaseMessage]
    injected_tokens: int
    decision: HydrationDecision


@dataclass
class DemandHydrationConfig:
    """按需水合与创造力保鲜配置契约。"""

    enable_implicit_routing: bool = True
    max_hydrated_cards_per_turn: int = 2
    creative_mode_keywords: tuple[str, ...] = (
        "brainstorm",
        "idea",
        "creative",
        "divergent",
        "头脑风暴",
        "创意",
        "畅想",
        "开放式探讨",
        "灵感",
    )
