"""个人画像与专业偏好全域按需水合与大模型创造力保鲜模块。

[INPUT]
- .demand_hydration_types: 强类型契约与配置
- .on_demand_context_hydrator: 核心按需水合与创造力保鲜引擎

[OUTPUT]
- 统一向外导出公共契约与核心类。

[POS]
- 位于 context_management/demand_hydration/__init__.py
"""

from .demand_hydration_types import (
    DemandHydrationConfig,
    HydratedContextEnvelope,
    HydrationDecision,
    HydrationTriggerMode,
    ProfileCardCategory,
    UserMemoryCard,
)
from .on_demand_context_hydrator import OnDemandContextHydrator

__all__ = [
    "DemandHydrationConfig",
    "HydratedContextEnvelope",
    "HydrationDecision",
    "HydrationTriggerMode",
    "OnDemandContextHydrator",
    "ProfileCardCategory",
    "UserMemoryCard",
]
