"""Grounded Dreaming, Provenance Anchoring, and Surgical Memory Unlearning toolkit.

[INPUT]
- toolkits.memory.dreaming.engine::GroundedDreamingEngine (POS:
  做梦认知聚类蒸馏引擎。在空闲周期执行跨会话事实聚类、共识加权、敏感信息红线拦截、
  多项目作用域隔离，并将结构化双向溯源锚点绑定至梦境日记条目。)
- toolkits.memory.dreaming.models::DreamDiaryEntry, DreamDiaryStatus, DreamSessionFragment,
  SurgicalUnlearnReport (POS: 做梦认知日记与溯源数据契约核心。定义跨会话认知洞察实体、审核与锁定状态枚举、
  不可篡改的双向溯源锚点集，以及外科手术式遗忘审计报告。)
- toolkits.memory.dreaming.provenance::MemoryProvenanceAnchor, ProjectScopeIsolationGuard,
  SensitiveProvenanceGuard (POS: 记忆溯源与安全治理核心组件。为认知事实提供不可篡改的消息级双向溯源锚点、
  阻断敏感凭据进入长期记忆的红线拦截器，以及杜绝跨项目上下文污染的作用域隔离门禁。)
- toolkits.memory.dreaming.scheduler::DreamingTriggerReason, GroundedDreamingScheduler (POS:
  记忆认知闲时整合调度中心。管理人类睡眠期记忆整合生理机制的后台模拟，
  涵盖空闲交互超时判定、夜间定时窗口检测、REM 历史会话窗口回溯重放管道， 以及多项目隔离作用域做梦编排。)
- toolkits.memory.dreaming.unlearn::SurgicalSessionMemoryUnlearner (POS: Surgical Session Memory Unlearning
  Operator.)

[OUTPUT]
- Package facade re-exporting 11 public names: DreamDiaryEntry, DreamDiaryStatus, DreamSessionFragment,
  DreamingTriggerReason, GroundedDreamingEngine, GroundedDreamingScheduler, MemoryProvenanceAnchor,
  ProjectScopeIsolationGuard, SensitiveProvenanceGuard, SurgicalSessionMemoryUnlearner,
  SurgicalUnlearnReport

[POS]
Grounded Dreaming, Provenance Anchoring, and Surgical Memory Unlearning toolkit.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.dreaming.cognitive_models import (
    CognitiveConsolidationReport,
    DreamCognitiveAction,
    DreamCognitiveActionType,
    DreamCognitiveCluster,
    DreamMotive,
    DreamMotiveType,
    DreamTargetMemoryType,
    GrowthDiaryEntry,
    HypotheticalDeduction,
)
from myrm_agent_harness.toolkits.memory.dreaming.cognitive_pipeline import (
    DreamCognitivePipeline,
)
from myrm_agent_harness.toolkits.memory.dreaming.engine import (
    GroundedDreamingEngine,
)
from myrm_agent_harness.toolkits.memory.dreaming.growth_diary import (
    GrowthDiaryGenerator,
)
from myrm_agent_harness.toolkits.memory.dreaming.models import (
    DreamDiaryEntry,
    DreamDiaryStatus,
    DreamingSynthesisReport,
    DreamSessionFragment,
    PrunedMemoryRecord,
    PruningDecisionKind,
    SurgicalUnlearnReport,
)
from myrm_agent_harness.toolkits.memory.dreaming.provenance import (
    MemoryProvenanceAnchor,
    ProjectScopeIsolationGuard,
    SensitiveProvenanceGuard,
)
from myrm_agent_harness.toolkits.memory.dreaming.pruner import (
    MemoryPruningEngine,
)
from myrm_agent_harness.toolkits.memory.dreaming.scheduler import (
    DreamingTriggerReason,
    GroundedDreamingScheduler,
)
from myrm_agent_harness.toolkits.memory.dreaming.synthesizer import (
    AutonomousDreamingSynthesizer,
)
from myrm_agent_harness.toolkits.memory.dreaming.tools import (
    DreamingMetaTools,
)
from myrm_agent_harness.toolkits.memory.dreaming.unlearn import (
    SurgicalSessionMemoryUnlearner,
)

__all__ = [
    "AutonomousDreamingSynthesizer",
    "CognitiveConsolidationReport",
    "DreamCognitiveAction",
    "DreamCognitiveActionType",
    "DreamCognitiveCluster",
    "DreamCognitivePipeline",
    "DreamDiaryEntry",
    "DreamDiaryStatus",
    "DreamMotive",
    "DreamMotiveType",
    "DreamSessionFragment",
    "DreamTargetMemoryType",
    "DreamingMetaTools",
    "DreamingSynthesisReport",
    "DreamingTriggerReason",
    "GroundedDreamingEngine",
    "GroundedDreamingScheduler",
    "GrowthDiaryEntry",
    "GrowthDiaryGenerator",
    "HypotheticalDeduction",
    "MemoryProvenanceAnchor",
    "MemoryPruningEngine",
    "ProjectScopeIsolationGuard",
    "PrunedMemoryRecord",
    "PruningDecisionKind",
    "SensitiveProvenanceGuard",
    "SurgicalSessionMemoryUnlearner",
    "SurgicalUnlearnReport",
]

