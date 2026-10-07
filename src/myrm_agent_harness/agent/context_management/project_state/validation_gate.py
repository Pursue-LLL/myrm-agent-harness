# [POS] myrm_agent_harness/agent/context_management/project_state/validation_gate.py
# [INPUT] ValidationAuditInput, ValidationAuditResult, LivingFact, FactPromotionStage, ProjectStateLivingFactLedger
# [OUTPUT] ValidationGatedPromotionGate

"""基于确定性验证结果的经验准入审计网关与状态晋升飞轮。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from .living_fact_ledger import ProjectStateLivingFactLedger
from .types import (
    FactPromotionStage,
    LivingFact,
    ValidationAuditInput,
    ValidationAuditResult,
)


class ValidationGatedPromotionGate:
    """验证结果准入审计网关，将确定性测试成果转化为高置信度知识沉淀。"""

    def __init__(self, ledger: ProjectStateLivingFactLedger) -> None:
        self._ledger = ledger

    def audit_validation(
        self, audit_input: ValidationAuditInput
    ) -> ValidationAuditResult:
        """执行验证结果审计，更新事实生命周期与晋升状态。"""
        existing = self._ledger.get_fact(
            audit_input.project_id, audit_input.fact_id
        )
        if not existing:
            return ValidationAuditResult(
                fact_id=audit_input.fact_id,
                new_stage=FactPromotionStage.CONFIRMED_FACT,
                validation_count=0,
                regression_count=0,
                is_promoted=False,
                recommend_skill_extraction=False,
                message=f"Fact {audit_input.fact_id} not found in ledger.",
            )

        now = datetime.now(UTC).isoformat()
        if audit_input.passed:
            new_val_count = existing.validation_count + 1
            new_reg_count = existing.regression_count
            new_stage = existing.promotion_stage
            is_promoted = False
            recommend_skill = False

            if existing.promotion_stage == FactPromotionStage.OBSERVATION or existing.promotion_stage == FactPromotionStage.PROJECT_EVENT:
                new_stage = FactPromotionStage.CONFIRMED_FACT
                is_promoted = True
            elif existing.promotion_stage == FactPromotionStage.CONFIRMED_FACT:
                # 经验复利：重复验证 ≥ 2 次且无回归，自动晋升为稳定经验 Knowledge
                if new_val_count >= 2 and new_reg_count == 0:
                    new_stage = FactPromotionStage.KNOWLEDGE
                    is_promoted = True
            elif existing.promotion_stage == FactPromotionStage.KNOWLEDGE:
                # 多次稳定复验 ≥ 4 次，建议下沉为可复用标准技能 Skill
                if new_val_count >= 4 and new_reg_count == 0:
                    new_stage = FactPromotionStage.SKILL
                    is_promoted = True
                    recommend_skill = True

            updated_metadata = dict(existing.metadata)
            if audit_input.test_summary:
                updated_metadata["last_validation_summary"] = (
                    audit_input.test_summary
                )

            updated_fact: LivingFact = replace(
                existing,
                validation_count=new_val_count,
                regression_count=new_reg_count,
                promotion_stage=new_stage,
                updated_at=now,
                metadata=updated_metadata,
            )
            self._ledger.record_fact(updated_fact)

            return ValidationAuditResult(
                fact_id=audit_input.fact_id,
                new_stage=new_stage,
                validation_count=new_val_count,
                regression_count=new_reg_count,
                is_promoted=is_promoted,
                recommend_skill_extraction=recommend_skill,
                message="Validation passed and recorded.",
            )
        else:
            # 验证失败或发生回归
            new_reg_count = existing.regression_count + 1
            new_stage = existing.promotion_stage
            # 若原本被视为稳定 Knowledge / Skill，发生回归则降级回 CONFIRMED_FACT 进行重新检视
            if existing.promotion_stage in (
                FactPromotionStage.KNOWLEDGE,
                FactPromotionStage.SKILL,
            ):
                new_stage = FactPromotionStage.CONFIRMED_FACT

            updated_metadata = dict(existing.metadata)
            if audit_input.test_summary:
                updated_metadata["last_regression_summary"] = (
                    audit_input.test_summary
                )

            updated_fact = replace(
                existing,
                regression_count=new_reg_count,
                promotion_stage=new_stage,
                updated_at=now,
                metadata=updated_metadata,
            )
            self._ledger.record_fact(updated_fact)

            return ValidationAuditResult(
                fact_id=audit_input.fact_id,
                new_stage=new_stage,
                validation_count=existing.validation_count,
                regression_count=new_reg_count,
                is_promoted=False,
                recommend_skill_extraction=False,
                message="Validation failed: regression count incremented.",
            )
