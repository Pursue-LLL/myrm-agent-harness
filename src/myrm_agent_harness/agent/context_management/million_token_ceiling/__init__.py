"""百万 Token 超大上下文动态自适应压实与双轨绝对上限守卫模块。

[INPUT]
- .million_token_ceiling_types: 强类型数据模型与枚举
- .million_token_ceiling_governor: 核心守卫引擎

[OUTPUT]
- 统一向外导出公共契约与核心类。

[POS]
- 位于 context_management/million_token_ceiling/__init__.py
"""

from .million_token_ceiling_governor import MillionTokenCeilingGovernor
from .million_token_ceiling_types import (
    CompactionTierAction,
    CompactionTrackType,
    ContextBudgetForecast,
    MillionTokenCeilingConfig,
    MillionTokenCompactionResult,
    OffloadedToolArtifact,
)

__all__ = [
    "CompactionTierAction",
    "CompactionTrackType",
    "ContextBudgetForecast",
    "MillionTokenCeilingConfig",
    "MillionTokenCompactionResult",
    "MillionTokenCeilingGovernor",
    "OffloadedToolArtifact",
]
