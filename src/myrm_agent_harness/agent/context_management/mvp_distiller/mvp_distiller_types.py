"""Strongly typed contracts for Complex Project MVP Scope Distiller and Stepwise Guide Suite (Item 214).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- ProjectComplexityLevel: Evaluated project complexity risk.
- ModuleSpec: Strongly typed specification of an identified architectural sub-module.
- PhaseScopePlan: Staged MVP phase execution milestone.
- MvpPhaseLifecycleState: State machine governing stepwise phase progression.
- DistillationOutcome: Complete telemetry output containing distilled plans and nudges.
- MvpDistillerConfig: Tunable configuration for complexity heuristics and limits.

[POS]
- Prevents context overflow, architectural conflicts, and half-baked abandoned code
- by distilling bloated requirements into a progressive 3-core-module MVP roadmap.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class ProjectComplexityLevel(str, enum.Enum):
    """Categorized complexity risk level of requested software project."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH_COMPLEXITY_RISK = "high_complexity_risk"


class MvpPhaseLifecycleState(str, enum.Enum):
    """Lifecycle progression state for phased MVP execution."""

    IDLE = "idle"
    PROPOSED = "proposed"
    PHASE_1_ACTIVE = "phase_1_active"
    PHASE_1_VERIFIED = "phase_1_verified"
    PHASE_NEXT_READY = "phase_next_ready"
    ALL_COMPLETED = "all_completed"


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """Strongly typed descriptor representing an extracted project functional domain."""

    module_id: str
    name: str
    description: str
    is_mvp_core: bool = False
    dependencies: list[str] = field(default_factory=list)
    estimated_risk_score: float = 1.0

    def to_dict(self) -> dict[str, object]:
        """Serializes module spec to dictionary."""
        return {
            "module_id": self.module_id,
            "name": self.name,
            "description": self.description,
            "is_mvp_core": self.is_mvp_core,
            "dependencies": list(self.dependencies),
            "estimated_risk_score": self.estimated_risk_score,
        }


@dataclass(frozen=True, slots=True)
class PhaseScopePlan:
    """Staged plan dividing complex functionality into executable milestones."""

    phase_index: int
    phase_name: str
    target_modules: list[str] = field(default_factory=list)
    deliverable_description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serializes phase scope plan to dictionary."""
        return {
            "phase_index": self.phase_index,
            "phase_name": self.phase_name,
            "target_modules": list(self.target_modules),
            "deliverable_description": self.deliverable_description,
            "acceptance_criteria": list(self.acceptance_criteria),
        }


@dataclass(frozen=True, slots=True)
class DistillationOutcome:
    """Comprehensive distillation evaluation outcome with telemetry."""

    complexity_level: ProjectComplexityLevel
    detected_modules: list[ModuleSpec]
    phased_plans: list[PhaseScopePlan]
    intervention_needed: bool
    distillation_prompt_nudge: str
    summary_card_markdown: str
    evaluation_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Serializes outcome to dictionary."""
        return {
            "complexity_level": self.complexity_level.value,
            "detected_modules": [m.to_dict() for m in self.detected_modules],
            "phased_plans": [p.to_dict() for p in self.phased_plans],
            "intervention_needed": self.intervention_needed,
            "distillation_prompt_nudge": self.distillation_prompt_nudge,
            "summary_card_markdown": self.summary_card_markdown,
            "evaluation_duration_ms": self.evaluation_duration_ms,
        }


@dataclass(slots=True)
class MvpDistillerConfig:
    """Configuration governing MVP scope distillation heuristics and boundaries."""

    max_mvp_core_modules: int = 3
    high_risk_module_threshold: int = 4
    auto_suggest_mvp: bool = True
    domain_keywords: dict[str, list[str]] = field(
        default_factory=lambda: {
            "auth": ["登录", "注册", "jwt", "auth", "oauth", "权限", "rbac", "user"],
            "data_storage": ["数据库", "orm", "sqlite", "postgres", "mysql", "model", "schema"],
            "core_presentation": ["首页", "展示", "ui", "view", "dashboard", "list", "详情页"],
            "commerce_payment": ["支付", "stripe", "alipay", "wechat_pay", "结算", "购物车", "checkout"],
            "order_management": ["订单", "退款", "物流", "发货", "order", "invoice"],
            "admin_portal": ["管理后台", "admin", "仪表盘", "运营", "audit_log", "系统配置"],
            "notification_search": ["搜索", "全文检索", "通知", "邮件", "短信", "websocket", "推送"],
        }
    )
