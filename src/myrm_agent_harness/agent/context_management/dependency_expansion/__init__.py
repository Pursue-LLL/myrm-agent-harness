"""全链路跨栈架构依赖展开图谱与任务复杂度自适应双轨调度套件。

[INPUT]
- agent.context_management.dependency_expansion.adaptive_complexity_governor::AdaptiveComplexityGovernor
  (POS: 任务复杂度动态自适应双轨调度器，轻任务极简直通车与长周期项目全量工作台自适应分流。)
-
  agent.context_management.dependency_expansion.dependency_graph_expander::ArchitecturalDependencyGraphExpander
  (POS: 全链路跨栈架构依赖展开图谱引擎，级联追踪 UI 组件到底层模型与历史架构决议。)
- agent.context_management.dependency_expansion.types::ArchitectureNode, ArchitectureNodeType,
  ComplexityClassification, DependencyEdge, DependencyEdgeType, DependencyGraphExpansionResult,
  TaskComplexityTrack (POS: 全链路跨栈架构依赖展开与任务复杂度自适应双轨调度核心类型定义。)

[OUTPUT]
- Package facade re-exporting 9 public names: AdaptiveComplexityGovernor,
  ArchitecturalDependencyGraphExpander, ArchitectureNode, ArchitectureNodeType, ComplexityClassification,
  DependencyEdge, DependencyEdgeType, DependencyGraphExpansionResult, TaskComplexityTrack

[POS]
全链路跨栈架构依赖展开图谱与任务复杂度自适应双轨调度套件。
"""

from .adaptive_complexity_governor import AdaptiveComplexityGovernor
from .dependency_graph_expander import ArchitecturalDependencyGraphExpander
from .types import (
    ArchitectureNode,
    ArchitectureNodeType,
    ComplexityClassification,
    DependencyEdge,
    DependencyEdgeType,
    DependencyGraphExpansionResult,
    TaskComplexityTrack,
)

__all__ = [
    "AdaptiveComplexityGovernor",
    "ArchitecturalDependencyGraphExpander",
    "ArchitectureNode",
    "ArchitectureNodeType",
    "ComplexityClassification",
    "DependencyEdge",
    "DependencyEdgeType",
    "DependencyGraphExpansionResult",
    "TaskComplexityTrack",
]
