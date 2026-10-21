"""全链路跨栈架构依赖展开与任务复杂度自适应双轨调度核心类型定义。

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ArchitectureNodeType: 跨栈架构实体节点类型。
- DependencyEdgeType: 架构拓扑实体间的级联依赖边类型。
- ArchitectureNode: 跨栈架构拓扑实体节点。
- DependencyEdge: 架构拓扑关联依赖边。
- DependencyGraphExpansionResult: 架构依赖级联展开与影响面计算结果切片。
- TaskComplexityTrack: 任务复杂度动态感知调度轨道枚举。
- ComplexityClassification: 任务复杂度分类判定与分流决策结果。

[POS]
全链路跨栈架构依赖展开与任务复杂度自适应双轨调度核心类型定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ArchitectureNodeType(StrEnum):
    """跨栈架构实体节点类型。"""

    COMPONENT = "component"  # 前端/UI 组件或核心业务模块
    DEPENDENCY = "dependency"  # 第三方库、图表引擎或运行时底层依赖
    API = "api"  # 后端正式 REST/RPC 接口契约
    DATA_MODEL = "data_model"  # 数据库表、实体或传输模型
    ARCHITECTURAL_DECISION = "architectural_decision"  # 历史架构选型决议或反模式被否决方案


class DependencyEdgeType(StrEnum):
    """架构拓扑实体间的级联依赖边类型。"""

    CALLS = "calls"  # 组件直接调用
    DEPENDS_ON = "depends_on"  # 依赖于底层组件或三方库
    EXPOSES_API = "exposes_api"  # 对外暴露接口
    BINDS_MODEL = "binds_model"  # 绑定持久化数据模型
    CONSTRAINED_BY = "constrained_by"  # 受物理或架构决议约束
    REJECTED_ALTERNATIVE = "rejected_alternative"  # 该方案已被否决 (反模式警示)


@dataclass(frozen=True)
class ArchitectureNode:
    """跨栈架构拓扑实体节点。"""

    node_id: str
    node_type: ArchitectureNodeType
    name: str
    file_path: str = ""
    description: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DependencyEdge:
    """架构拓扑关联依赖边。"""

    source_id: str
    target_id: str
    edge_type: DependencyEdgeType
    description: str = ""


@dataclass(frozen=True)
class DependencyGraphExpansionResult:
    """架构依赖级联展开与影响面计算结果切片。"""

    target_node_id: str
    visited_nodes: list[ArchitectureNode]
    blast_radius_score: float  # 变更影响面得分 (0.0 - 100.0)
    critical_constraints: list[str]
    rejected_alternatives: list[str]
    formatted_expansion_block: str


class TaskComplexityTrack(StrEnum):
    """任务复杂度动态感知调度轨道枚举。"""

    FAST_LEAN = "fast_lean"  # 极简直通车: 极速执行，跳过重型账本写盘，0.1s 响应
    FULL_WORKBENCH = "full_workbench"  # 完整工作台: 激活依赖图谱展开、决策追踪与验证闭环


@dataclass(frozen=True)
class ComplexityClassification:
    """任务复杂度分类判定与分流决策结果。"""

    track: TaskComplexityTrack
    reason: str
    estimated_token_overhead: int
    bypass_state_sync: bool
