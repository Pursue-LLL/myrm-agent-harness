# [POS] myrm_agent_harness/agent/context_management/project_state/types.py
# [INPUT] None (纯领域类型与数据模型定义)
# [OUTPUT] ProjectFactType, FactPromotionStage, LivingFact, ProjectionQuery, ProjectedContextSlice, ValidationAuditInput, ValidationAuditResult

"""面向长期项目的动态事实状态账本与上下文投影核心类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ProjectFactType(StrEnum):
    """项目事实类型枚举。"""

    DECISION = "decision"  # 已采纳的架构或方案决策
    REJECTED_ALTERNATIVE = "rejected_alternative"  # 被否决的方案及否决原因 (反模式)
    CONSTRAINT = "constraint"  # 经过验证不可触碰的物理边界与硬性约束
    INTERFACE_CONTRACT = "interface_contract"  # 正式生效的 API 契约与数据接口
    VALIDATION_RESULT = "validation_result"  # 确定性验收测试结论与修复成果


class FactPromotionStage(StrEnum):
    """信息晋升阶梯阶段枚举。"""

    OBSERVATION = "observation"  # 临时观察
    PROJECT_EVENT = "project_event"  # 项目事件
    CONFIRMED_FACT = "confirmed_fact"  # 已确认事实
    KNOWLEDGE = "knowledge"  # 经过多次验证的稳定经验
    SKILL = "skill"  # 已下沉固化的可执行技能能力


@dataclass(frozen=True)
class LivingFact:
    """长期项目生命周期中的动态结构化事实条目。"""

    fact_id: str
    project_id: str
    fact_type: ProjectFactType
    title: str
    content: str
    target_components: list[str] = field(default_factory=list)
    reason_or_constraint: str = ""
    validation_count: int = 0
    regression_count: int = 0
    promotion_stage: FactPromotionStage = FactPromotionStage.CONFIRMED_FACT
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectionQuery:
    """四层级联上下文投影查询请求参数。"""

    project_id: str
    target_task: str
    target_components: list[str] = field(default_factory=list)
    token_budget: int = 1500


@dataclass(frozen=True)
class ProjectedContextSlice:
    """四层级联投影流水线萃取生成的动态上下文切片。"""

    project_id: str
    facts: list[LivingFact]
    formatted_prompt_block: str
    total_tokens_estimated: int
    projected_by_tier: dict[str, int]


@dataclass(frozen=True)
class ValidationAuditInput:
    """验证结果准入审计输入参数。"""

    project_id: str
    fact_id: str
    passed: bool
    test_summary: str = ""


@dataclass(frozen=True)
class ValidationAuditResult:
    """验证结果准入审计与状态晋升结果。"""

    fact_id: str
    new_stage: FactPromotionStage
    validation_count: int
    regression_count: int
    is_promoted: bool
    recommend_skill_extraction: bool
    message: str = ""
