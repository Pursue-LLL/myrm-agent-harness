"""显式工作区探索守卫与自主扫盘抑制套件模块。

[INPUT]
- workspace_guard_types.py: 契约模型
- workspace_guard_engine.py: 核心引擎与过滤器

[OUTPUT]
- 导出 WorkspaceAccessPolicy, ExplorationDecisionStatus, ExplorationGuardDecision, WorkspaceGuardConfig, PromptCrawlSuppressionFilter, WorkspaceExplorationGuardEngine

[POS]
- 位于 context_management/workspace_guard/__init__.py
"""

from .workspace_guard_engine import (
    PromptCrawlSuppressionFilter,
    WorkspaceExplorationGuardEngine,
)
from .workspace_guard_types import (
    ExplorationDecisionStatus,
    ExplorationGuardDecision,
    WorkspaceAccessPolicy,
    WorkspaceGuardConfig,
)

__all__ = [
    "ExplorationDecisionStatus",
    "ExplorationGuardDecision",
    "PromptCrawlSuppressionFilter",
    "WorkspaceAccessPolicy",
    "WorkspaceExplorationGuardEngine",
    "WorkspaceGuardConfig",
]
