"""双阶段崩溃自愈会话自动提交与三维经验沉淀模块。

[INPUT]
- .session_commit_types: 强类型契约与策略配置
- .two_phase_session_commit_engine: 核心双阶段提交与自愈引擎

[OUTPUT]
- 统一向外导出公共契约与核心类。

[POS]
- 位于 context_management/session_commit/__init__.py
"""

from .session_commit_types import (
    CommitJobStatus,
    CommitTriggerReason,
    ExperienceLearningItem,
    Phase1SnapshotResult,
    ProjectGuidelineItem,
    SessionCommitJob,
    SessionCommitPolicyConfig,
    TriDimensionalDistillationResult,
    UserPreferenceItem,
)
from .two_phase_session_commit_engine import TwoPhaseSessionCommitEngine

__all__ = [
    "CommitJobStatus",
    "CommitTriggerReason",
    "ExperienceLearningItem",
    "Phase1SnapshotResult",
    "ProjectGuidelineItem",
    "SessionCommitJob",
    "SessionCommitPolicyConfig",
    "TriDimensionalDistillationResult",
    "TwoPhaseSessionCommitEngine",
    "UserPreferenceItem",
]
