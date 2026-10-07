"""单任务瞬态上下文防污染隔离、最终产物干净汇流与夜间定时无损资产沉淀套件。

导出的主要类与契约：
- CleanPodArchivalEngine: 瞬态纯净上下文隔离舱与夜间资产归集中枢引擎
- CleanPodArchivalConfig: 隔离舱与夜间归集策略配置契约
- EphemeralCleanPodDescriptor: 瞬态纯净 Pod 上下文隔离舱描述契约
- NightlyArchivalJob: 夜间定时资产沉淀与多维数据落盘任务契约
- NightlyArchivalStatus: 夜间自动化资产沉淀状态枚举
- PodLifecycleState: 瞬态隔离舱生命周期状态枚举
- TaskDeliverableContract: 瞬态任务结构化交付物契约
"""

from .clean_pod_archival_engine import CleanPodArchivalEngine
from .clean_pod_archival_types import (
    CleanPodArchivalConfig,
    EphemeralCleanPodDescriptor,
    NightlyArchivalJob,
    NightlyArchivalStatus,
    PodLifecycleState,
    TaskDeliverableContract,
)

__all__ = [
    "CleanPodArchivalConfig",
    "CleanPodArchivalEngine",
    "EphemeralCleanPodDescriptor",
    "NightlyArchivalJob",
    "NightlyArchivalStatus",
    "PodLifecycleState",
    "TaskDeliverableContract",
]
