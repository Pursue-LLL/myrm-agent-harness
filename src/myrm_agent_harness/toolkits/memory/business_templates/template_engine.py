# [POS]: myrm_agent_harness.toolkits.memory.business_templates.template_engine
# [INPUT]: .models (BusinessExperienceTemplate, EscalationDecision, EscalationAction, EscalationReason, EscalationEvaluationContext, ValidationRecord, TemplateCategory), .seed_templates (SEED_TEMPLATES)
# [OUTPUT]: BusinessTemplateEngine

"""Engine coordinating business experience templates and escalation decision evaluations.

P0 delivery for Item 107 in topic_01 memory roadmap.
Supports querying pre-seeded templates, continuous feedback evolution, and evaluating
customer retail escalation gates.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.business_templates.models import (
    BusinessExperienceTemplate,
    EscalationAction,
    EscalationDecision,
    EscalationEvaluationContext,
    EscalationReason,
    TemplateCategory,
    ValidationRecord,
)
from myrm_agent_harness.toolkits.memory.business_templates.seed_templates import SEED_TEMPLATES

logger = logging.getLogger(__name__)


class BusinessTemplateEngine:
    """Manages business experience templates and executes human escalation gate evaluations."""

    def __init__(self, initial_templates: list[BusinessExperienceTemplate] | None = None) -> None:
        self._templates: dict[str, BusinessExperienceTemplate] = {}
        self._validation_records: list[ValidationRecord] = []

        templates_to_load = initial_templates if initial_templates is not None else SEED_TEMPLATES
        for tpl in templates_to_load:
            self._templates[tpl.template_id] = tpl.model_copy(deep=True)

    def list_templates(self, category: TemplateCategory | None = None) -> list[BusinessExperienceTemplate]:
        """List all available templates, optionally filtered by category."""
        if category is None:
            return list(self._templates.values())
        return [tpl for tpl in self._templates.values() if tpl.category == category]

    def get_template(self, template_id: str) -> BusinessExperienceTemplate | None:
        """Retrieve a specific template by identifier."""
        return self._templates.get(template_id)

    def search_templates(self, query: str) -> list[BusinessExperienceTemplate]:
        """Search templates by keyword matching name, summary, or tags."""
        q = query.strip().lower()
        if not q:
            return self.list_templates()

        results: list[BusinessExperienceTemplate] = []
        for tpl in self._templates.values():
            in_name = q in tpl.name.lower()
            in_summary = q in tpl.summary.lower()
            in_tags = any(q in tag.lower() for tag in tpl.tags)
            if in_name or in_summary or in_tags:
                results.append(tpl)
        return results

    def evaluate_escalation(self, context: EscalationEvaluationContext) -> EscalationDecision:
        """Evaluate an operational or retail context against escalation boundary gates."""
        req_context: dict[str, str] = {
            "order_id": context.order_id or "unknown",
            "user_id": context.user_id or "unknown",
            "intent": context.intent,
            "shipment_status": context.shipment_status,
        }

        # Gate 1: Custom product or policy ambiguity -> escalate
        if context.is_custom_order or not context.policy_clear:
            reason = EscalationReason.POLICY_AMBIGUITY
            msg = (
                "订单涉及特殊定制品类或退换货政策存在歧义条款，"
                "已阻断自主办理并触发人工客服审核。"
            )
            req_context["policy_issue"] = "custom_order" if context.is_custom_order else "unclear_terms"
            return EscalationDecision(
                action=EscalationAction.ESCALATE_TO_HUMAN,
                reason=reason,
                message=msg,
                required_context=req_context,
                suggested_skill_or_tool="route_to_human_specialist",
            )

        # Gate 2: Inventory shortage -> escalate
        if not context.inventory_available:
            reason = EscalationReason.INVENTORY_SHORTAGE
            msg = "用户期望更换的目标商品规格当前处于断码缺货状态，无法承诺自主发货，转交人工协商替代方案。"
            req_context["stock_status"] = "out_of_stock"
            return EscalationDecision(
                action=EscalationAction.ESCALATE_TO_HUMAN,
                reason=reason,
                message=msg,
                required_context=req_context,
                suggested_skill_or_tool="escalate_out_of_stock_case",
            )

        # Gate 3: User dispute count >= 2 -> escalate
        if context.user_dispute_count >= 2:
            reason = EscalationReason.USER_DISPUTE_FAILED
            msg = f"检测到用户已进行 {context.user_dispute_count} 次纠偏或存在严重分歧，触发防死循环争议熔断并转人工。"
            req_context["dispute_count"] = str(context.user_dispute_count)
            return EscalationDecision(
                action=EscalationAction.ESCALATE_TO_HUMAN,
                reason=reason,
                message=msg,
                required_context=req_context,
                suggested_skill_or_tool="connect_dispute_arbitrator",
            )

        # Gate 4: Invalid warranty/window -> escalate
        if not context.warranty_valid:
            reason = EscalationReason.ANOMALOUS_ORDER
            msg = "订单已超过售后有效保修期或退换时限，超出常规自主办理权限，转由人工客服复核。"
            req_context["warranty_status"] = "expired"
            return EscalationDecision(
                action=EscalationAction.ESCALATE_TO_HUMAN,
                reason=reason,
                message=msg,
                required_context=req_context,
                suggested_skill_or_tool="escalate_warranty_exception",
            )

        # Safe path: automated execution
        if context.user_confirmed:
            msg = "所有先问与必查前置条件已验证通过，且用户已显式确认明细，允许自主执行办理。"
            return EscalationDecision(
                action=EscalationAction.PROCEED_AUTOMATED,
                reason=EscalationReason.NONE,
                message=msg,
                required_context=req_context,
                suggested_skill_or_tool="commit_retail_exchange",
            )

        msg = "前置条件验证通过，下一步必须获得用户显式确认后方可调用换货单提交工具。"
        return EscalationDecision(
            action=EscalationAction.PROCEED_AUTOMATED,
            reason=EscalationReason.NONE,
            message=msg,
            required_context=req_context,
            suggested_skill_or_tool="request_user_confirmation",
        )

    def record_validation(
        self,
        template_id: str,
        is_validated: bool,
        note: str = "",
    ) -> ValidationRecord | None:
        """Record operator or trajectory validation feedback to evolve template confidence."""
        tpl = self._templates.get(template_id)
        if tpl is None:
            return None

        now_str = datetime.now(UTC).isoformat()
        if is_validated:
            tpl.validated_count += 1
        else:
            tpl.rejected_count += 1
        tpl.last_validated_at = now_str

        rec = ValidationRecord(
            record_id=f"val_{uuid.uuid4().hex[:8]}",
            template_id=template_id,
            is_validated=is_validated,
            note=note,
            timestamp=now_str,
        )
        self._validation_records.append(rec)
        logger.info(
            "Recorded validation for template %s (validated=%s, total_val=%d, total_rej=%d)",
            template_id,
            is_validated,
            tpl.validated_count,
            tpl.rejected_count,
        )
        return rec

    def export_as_procedure_memories(self) -> list:
        """Export stored experience templates into standard ProcedureMemoryEntry items."""
        from myrm_agent_harness.toolkits.memory.procedure_experience.models import (
            ProcedureMemoryEntry,
        )

        entries: list[ProcedureMemoryEntry] = []
        for tpl in self._templates.values():
            steps = [f"{s.step_index}. {s.name}: {s.description}" for s in tpl.checklist_steps]
            entry = ProcedureMemoryEntry(
                entry_id=tpl.template_id,
                name=tpl.name,
                retrieval_anchor=f"{tpl.name} {' '.join(tpl.tags)}",
                operation_intent=tpl.summary,
                preconditions=tpl.boundary_conditions,
                immutable_boundary=[s.validation_rule for s in tpl.checklist_steps if s.mandatory],
                procedure_steps=steps,
                write_field_provenance={"template_version": tpl.version, "category": tpl.category.value},
                anti_patterns=["跳过前置检查步骤直接执行写入或决策", "在条件不满足时未经用户显式确认直接办理"],
                applicability=tpl.tags,
                negative_applicability=["不受支持的非结构化未知领域任务"],
                confidence=1.0,
                source_session_id=tpl.sample_trajectory_ref or None,
            )
            entries.append(entry)
        return entries

