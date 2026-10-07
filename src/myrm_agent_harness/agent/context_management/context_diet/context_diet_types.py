"""强类型契约定义：常设全局背景按需技能化、上下文开销透明透视与大模型创造力防束缚套件。

[INPUT]
- 无外部动态依赖，定义开局底噪要素枚举、Token账单契约、Persona蒸馏技能契约与节食配置契约。

[OUTPUT]
- ContextComponentKind: 开局上下文底噪构成要素枚举
- ComponentTokenAuditItem: 单要素 Token 审计账单契约
- ContextDietBudgetBill: 会话开局五要素底噪透视总账单契约
- DistilledSkillCard: 静态 Persona 蒸馏后的按需技能卡片契约
- ContextDietConfig: 上下文节食与透明账单配置契约

[POS]
- 位于 context_management/context_diet/context_diet_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence


class ContextComponentKind(StrEnum):
    """会话开局五大固定底噪要素分类。"""

    SYSTEM_PROMPT = "system_prompt"
    TOOL_SCHEMAS = "tool_schemas"
    SKILLS_INDEX = "skills_index"
    MEMORY_BRIEF = "memory_brief"
    ENVIRONMENT_FACTS = "environment_facts"
    STATIC_PERSONA = "static_persona"


@dataclass(frozen=True)
class ComponentTokenAuditItem:
    """单要素 Token 开销审计条目契约。"""

    component_kind: ContextComponentKind
    raw_char_count: int
    estimated_tokens: int
    ratio_of_budget: float  # 占开局总底噪的比例 (0.0 ~ 1.0)
    is_bloated: bool
    recommendation: str


@dataclass(frozen=True)
class ContextDietBudgetBill:
    """会话开局五要素底噪透视总账单契约。"""

    total_opening_tokens: int
    total_window_capacity: int
    opening_overhead_percent: float  # 占总窗口容量比例 (0.0 ~ 100.0)
    components: tuple[ComponentTokenAuditItem, ...]
    estimated_ttft_ms: float  # 预估 Prefill 首字耗时 (毫秒)
    potential_savings_tokens: int
    audited_at_iso: str


@dataclass(frozen=True)
class DistilledSkillCard:
    """静态 Persona 蒸馏后的按需技能卡片契约。"""

    skill_name: str
    trigger_command: str
    skeleton_pointer: str
    full_content: str
    token_savings: int
    created_at_iso: str


@dataclass
class ContextDietConfig:
    """上下文节食与透明账单配置契约。"""

    total_window_capacity: int = 128_000
    max_healthy_opening_ratio: float = 0.12  # 开局底噪超过窗口 12% 标记警告
    ttft_ms_per_thousand_tokens: float = 80.0  # 预估本地/云端模型每 1k tokens prefill 耗时 (ms)
    persona_bloat_char_threshold: int = 600  # 超过 600 字符的 Persona 建议蒸馏为技能
    token_char_ratio: float = 3.5  # 启发式字符转 Token 换算比
