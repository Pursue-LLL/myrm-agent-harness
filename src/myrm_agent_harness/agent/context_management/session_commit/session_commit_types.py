"""强类型契约定义：双阶段崩溃自愈会话自动提交与三维经验沉淀套件。

[INPUT]
- 无外部动态依赖，定义双阶段提交、持久化队列与三维沉淀领域模型。

[OUTPUT]
- CommitTriggerReason: 提交触发原因枚举
- CommitJobStatus: 异步作业状态枚举 (PENDING / IN_PROGRESS / COMPLETED / FAILED)
- UserPreferenceItem: 用户偏好沉淀项
- ExperienceLearningItem: 智能体踩坑经验与排障教训项
- ProjectGuidelineItem: 项目/组织新规范沉淀项
- TriDimensionalDistillationResult: 三维经验提炼输出契约
- SessionCommitJob: 持久化作业契约
- Phase1SnapshotResult: Phase 1 毫秒级快照切分结果
- SessionCommitPolicyConfig: 自动提交策略配置

[POS]
- 位于 context_management/session_commit/session_commit_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum


class CommitTriggerReason(StrEnum):
    """会话提交触发原因枚举。"""

    TOKEN_THRESHOLD = "token_threshold"
    TURNS_THRESHOLD = "turns_threshold"
    IDLE_TIMEOUT = "idle_timeout"
    EXPLICIT_FINISH = "explicit_finish"


class CommitJobStatus(StrEnum):
    """提交任务持久化生命周期状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class UserPreferenceItem:
    """沉淀的用户个人偏好维度契约。"""

    category: str
    preference_text: str
    confidence_score: float


@dataclass(frozen=True)
class ExperienceLearningItem:
    """沉淀的智能体经验与排障教训维度契约。"""

    problem_encountered: str
    root_cause: str
    resolution: str
    context_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectGuidelineItem:
    """沉淀的组织与项目规范演进维度契约。"""

    rule_name: str
    rule_statement: str
    scope: str


@dataclass(frozen=True)
class TriDimensionalDistillationResult:
    """三维经验提炼综合输出结果契约。"""

    job_id: str
    session_id: str
    preferences: list[UserPreferenceItem]
    learnings: list[ExperienceLearningItem]
    guidelines: list[ProjectGuidelineItem]
    distilled_at_epoch: float


@dataclass
class SessionCommitJob:
    """磁盘持久化可恢复的提交任务契约。"""

    job_id: str
    session_id: str
    trigger_reason: CommitTriggerReason
    status: CommitJobStatus
    message_count: int
    archived_payload_path: str
    created_at_epoch: float
    updated_at_epoch: float
    retry_count: int = 0
    error_message: str = ""


@dataclass(frozen=True)
class Phase1SnapshotResult:
    """Phase 1 毫秒级快照切割结果契约。"""

    job_id: str
    session_id: str
    live_messages_retained: int
    archived_messages_count: int
    status: str
    prepared_at_epoch: float


@dataclass
class SessionCommitPolicyConfig:
    """自适应会话提交策略网关配置。"""

    max_uncommitted_tokens: int = 150_000
    max_uncommitted_turns: int = 50
    idle_timeout_seconds: float = 1800.0
    live_window_turns: int = 5
    max_retry_attempts: int = 3
