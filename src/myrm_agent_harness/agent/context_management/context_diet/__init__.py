"""常设全局背景按需技能化、上下文开销透明透视与大模型创造力防束缚套件模块。

[INPUT]
- context_diet_types.py: 核心契约数据结构
- context_diet_engine.py: 核心引擎实现

[OUTPUT]
- 导出 ContextComponentKind, ComponentTokenAuditItem, ContextDietBudgetBill, DistilledSkillCard, ContextDietConfig, ContextDietEngine

[POS]
- 位于 context_management/context_diet/__init__.py
"""

from .context_diet_engine import ContextDietEngine
from .context_diet_types import (
    ComponentTokenAuditItem,
    ContextComponentKind,
    ContextDietBudgetBill,
    ContextDietConfig,
    DistilledSkillCard,
)

__all__ = [
    "ComponentTokenAuditItem",
    "ContextComponentKind",
    "ContextDietBudgetBill",
    "ContextDietConfig",
    "ContextDietEngine",
    "DistilledSkillCard",
]
