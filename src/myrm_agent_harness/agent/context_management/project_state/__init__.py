"""面向长期项目的动态事实状态账本与上下文投影流水线套件。

[INPUT]
- agent.context_management.project_state.context_projection_engine::FourTierContextProjectionEngine (POS:
  面向长期项目的四层级联动态上下文投影流水线引擎。)
- agent.context_management.project_state.living_fact_ledger::ProjectStateLivingFactLedger (POS:
  长期项目动态事实状态账本管理器，统一纳管已决议方案、被否决路径与硬性物理约束。)
- agent.context_management.project_state.types::FactPromotionStage, LivingFact, ProjectFactType,
  ProjectedContextSlice, ProjectionQuery, ValidationAuditInput, ValidationAuditResult (POS:
  面向长期项目的动态事实状态账本与上下文投影核心类型定义。)
- agent.context_management.project_state.validation_gate::ValidationGatedPromotionGate (POS:
  基于确定性验证结果的经验准入审计网关与状态晋升飞轮。)

[OUTPUT]
- Package facade re-exporting 10 public names: FactPromotionStage, FourTierContextProjectionEngine,
  LivingFact, ProjectFactType, ProjectStateLivingFactLedger, ProjectedContextSlice, ProjectionQuery,
  ValidationAuditInput, ValidationAuditResult, ValidationGatedPromotionGate

[POS]
面向长期项目的动态事实状态账本与上下文投影流水线套件。
"""

from .context_projection_engine import FourTierContextProjectionEngine
from .living_fact_ledger import ProjectStateLivingFactLedger
from .types import (
    FactPromotionStage,
    LivingFact,
    ProjectedContextSlice,
    ProjectFactType,
    ProjectionQuery,
    ValidationAuditInput,
    ValidationAuditResult,
)
from .validation_gate import ValidationGatedPromotionGate

__all__ = [
    "FactPromotionStage",
    "FourTierContextProjectionEngine",
    "LivingFact",
    "ProjectFactType",
    "ProjectStateLivingFactLedger",
    "ProjectedContextSlice",
    "ProjectionQuery",
    "ValidationAuditInput",
    "ValidationAuditResult",
    "ValidationGatedPromotionGate",
]
