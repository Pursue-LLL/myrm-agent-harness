"""显式工作区探索守卫与自主扫盘抑制套件强类型契约定义。

[INPUT]
- 无外部动态依赖，定义工作区访问策略枚举、对抗性意图过滤契约与守卫裁决契约。

[OUTPUT]
- WorkspaceAccessPolicy: 工作区访问策略三档枚举 (EXPLICIT_ONLY, ON_DEMAND, AUTO_INDEX)
- ExplorationDecisionStatus: 工具探索拦截裁决状态枚举 (ALLOWED, REJECTED_BY_EXPLICIT_RULE, REJECTED_BY_PROMPT_SUPPRESSION, REJECTED_DEPTH_EXCEEDED)
- ExplorationGuardDecision: 探索准入裁决结果契约
- WorkspaceGuardConfig: 工作区守卫配置契约

[POS]
- 位于 context_management/workspace_guard/workspace_guard_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum


class WorkspaceAccessPolicy(StrEnum):
    """会话级工作区目录访问策略三态枚举。"""

    EXPLICIT_ONLY = "explicit_only"  # 绝对静默：仅允许用户显式提及路径，严禁自主探盘
    ON_DEMAND = "on_demand"          # 按需精准：单层精准探测，禁止跨级递归
    AUTO_INDEX = "auto_index"        # 全量自动：开发工程场景下的全面语义与目录索引


class ExplorationDecisionStatus(StrEnum):
    """工具探索拦截裁决状态。"""

    ALLOWED = "allowed"
    REJECTED_BY_EXPLICIT_RULE = "rejected_by_explicit_rule"
    REJECTED_BY_PROMPT_SUPPRESSION = "rejected_by_prompt_suppression"
    REJECTED_DEPTH_EXCEEDED = "rejected_depth_exceeded"


@dataclass(frozen=True)
class ExplorationGuardDecision:
    """工作区探索工具准入裁决结果契约。"""

    status: ExplorationDecisionStatus
    allowed: bool
    effective_policy: WorkspaceAccessPolicy
    tool_name: str
    target_path: str
    reason: str
    feedback_message: str  # 给大模型的友好中文指引（避免破坏推理流程）
    suppression_triggered_by_prompt: bool


@dataclass
class WorkspaceGuardConfig:
    """工作区探索守卫配置契约。"""

    default_policy: WorkspaceAccessPolicy = WorkspaceAccessPolicy.ON_DEMAND
    max_on_demand_depth: int = 1
    exploration_tool_names: tuple[str, ...] = (
        "list_dir",
        "view_directory",
        "directory_analysis",
        "glob",
        "find_files",
        "workspace_tree",
        "list_directory",
    )
    # 提示词对抗性抑制否定关键词集合
    crawl_suppression_keywords: tuple[str, ...] = (
        "不要翻看文件夹",
        "不要查看文件夹",
        "不要检查我的文件夹",
        "无需查看本地代码",
        "不用看代码",
        "不用扫描目录",
        "只回答理论",
        "只讨论概念",
        "do not check my folder",
        "don't check folder",
        "no need to check files",
        "theory only",
    )
