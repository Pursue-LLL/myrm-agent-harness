"""强类型契约定义：涌现式注意力清单、海量通知意图过滤器与言行错位智能对照套件。

[INPUT]
- 无外部动态依赖，定义行为轨迹、注意力涌现、通知过滤与言行 Diff 契约。

[OUTPUT]
- UserActionTraceKind: 行为轨迹类型枚举
- ActionTraceEvent: 用户跨应用行为轨迹事件契约
- EmergentAttentionItem: 涌现出的单项注意力聚焦实体
- EmergentAttentionDossier: 动态注意力流综合档案
- InboundNotification: 入站通知消息契约
- SieveDecision: 通知过滤决策枚举 (即时投递 / 批次摘要 / 静默归档)
- NotificationSieveResult: 通知筛查结果
- StatedIntention: 用户口头声称的优先级意图契约
- IntentionActionDiffItem: 单个项目的言行错位对照条目
- IntentionActionDiffReport: 言行错位自动化对照报告

[POS]
- 位于 context_management/emergent_attention/emergent_attention_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum


class UserActionTraceKind(StrEnum):
    """跨应用行为轨迹类别枚举。"""

    IM_REPLY = "im_reply"
    EMAIL_DISPATCH = "email_dispatch"
    CODE_COMMIT = "code_commit"
    DOC_EDIT = "doc_edit"
    CALENDAR_EVENT = "calendar_event"


@dataclass(frozen=True)
class ActionTraceEvent:
    """用户数字足迹行为事件契约。"""

    trace_id: str
    channel: str
    kind: UserActionTraceKind
    title: str
    summary: str
    duration_minutes: int
    timestamp_epoch: float
    project_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EmergentAttentionItem:
    """从真实行为轨迹中涌现出的单项核心注意力条目。"""

    project_name: str
    attention_score: float
    last_active_epoch: float
    key_progress: str
    current_blocker: str
    estimated_time_spent_mins: int


@dataclass(frozen=True)
class EmergentAttentionDossier:
    """当前实际注意力清单综合档案。"""

    generated_at_epoch: float
    items: list[EmergentAttentionItem]
    primary_focus: str
    total_tracked_minutes: int


class SieveDecision(StrEnum):
    """入站通知智能过滤决策枚举。"""

    DELIVER_IMMEDIATELY = "deliver_immediately"
    DIGEST_BATCH = "digest_batch"
    SILENT_ARCHIVE = "silent_archive"


@dataclass(frozen=True)
class InboundNotification:
    """跨渠道入站通知与消息契约。"""

    notification_id: str
    channel: str
    sender: str
    content: str
    urgency_hint: str
    project_tag: str
    requires_approval: bool = False


@dataclass(frozen=True)
class NotificationSieveResult:
    """高信噪比入站通知筛查结果。"""

    notification_id: str
    decision: SieveDecision
    relevance_score: float
    route_reason: str


@dataclass(frozen=True)
class StatedIntention:
    """用户口头/计划设定的优先级目标契约。"""

    project_name: str
    target_percentage: float
    priority_rank: int


@dataclass(frozen=True)
class IntentionActionDiffItem:
    """项目维度的言行错位自动化对比条目。"""

    project_name: str
    stated_percentage: float
    actual_percentage: float
    diff_percentage: float
    is_neglected: bool
    is_over_invested: bool
    drift_comment: str


@dataclass(frozen=True)
class IntentionActionDiffReport:
    """言行错位分析总览报告。"""

    overall_drift_index: float
    items: list[IntentionActionDiffItem]
    top_drift_warnings: list[str]
    analyzed_epoch: float
