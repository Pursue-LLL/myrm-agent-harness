"""强类型契约定义：单任务瞬态上下文防污染隔离、最终产物干净汇流与夜间定时无损资产沉淀套件。

[INPUT]
- 无外部动态依赖，定义瞬态隔离舱状态、交付物契约、描述符与夜间定时无损归集契约。

[OUTPUT]
- PodLifecycleState: 瞬态隔离舱生命周期状态枚举
- NightlyArchivalStatus: 夜间自动化资产沉淀状态枚举
- TaskDeliverableContract: 瞬态任务结构化交付物契约
- EphemeralCleanPodDescriptor: 瞬态纯净 Pod 上下文隔离舱描述契约
- NightlyArchivalJob: 夜间定时资产沉淀与多维数据落盘任务契约
- CleanPodArchivalConfig: 隔离舱与夜间归集策略配置契约

[POS]
- 位于 context_management/clean_pod_archival/clean_pod_archival_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence


class PodLifecycleState(StrEnum):
    """瞬态纯净上下文隔离舱生命周期状态。"""

    SPAWNED_ISOLATED = "spawned_isolated"
    EXECUTING_TASK = "executing_task"
    DELIVERABLE_EXTRACTED = "deliverable_extracted"
    RETIRED_DISCARDED = "retired_discarded"


class NightlyArchivalStatus(StrEnum):
    """夜间定时资产沉淀状态。"""

    SCHEDULED_IDLE = "scheduled_idle"
    RUNNING_HARVEST = "running_harvest"
    COMPLETED_INDEXED = "completed_indexed"
    FAILED = "failed"


@dataclass(frozen=True)
class TaskDeliverableContract:
    """瞬态任务完成提取的标准结构化交付物契约。"""

    deliverable_id: str
    task_topic: str
    content_payload: str
    media_uris: tuple[str, ...] = field(default_factory=tuple)
    extracted_metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    created_at_iso: str = ""


@dataclass(frozen=True)
class EphemeralCleanPodDescriptor:
    """瞬态纯净 Pod 上下文隔离舱描述契约。"""

    pod_id: str
    parent_session_id: str
    task_topic: str
    isolated_instructions: str
    state: PodLifecycleState = PodLifecycleState.SPAWNED_ISOLATED
    deliverables: tuple[TaskDeliverableContract, ...] = field(default_factory=tuple)
    turn_count: int = 0
    spawned_at_iso: str = ""
    retired_at_iso: str = ""


@dataclass(frozen=True)
class NightlyArchivalJob:
    """夜间定时无损资产沉淀任务契约。"""

    job_id: str
    session_ids: tuple[str, ...]
    target_storage_prefix: str
    status: NightlyArchivalStatus = NightlyArchivalStatus.SCHEDULED_IDLE
    harvested_assets_count: int = 0
    table_records_count: int = 0
    scheduled_hour_utc: int = 3
    summary_report: str = ""
    updated_at_iso: str = ""


@dataclass
class CleanPodArchivalConfig:
    """瞬态隔离与夜间归集配置契约。"""

    enable_prompt_sanitization: bool = True
    auto_retire_on_deliverable: bool = True
    default_nightly_cron_hour: int = 3
    preserve_raw_deliverables: bool = True
    max_active_pods_per_session: int = 8
