# [POS]: tests.unit.toolkits.memory.test_business_scenario_templates_suite
# [INPUT]: myrm_agent_harness.toolkits.memory.business_templates
# [OUTPUT]: Unit test suite for Item 107 business templates and escalation boundary gate

"""Unit test suite for business scenario experience templates and escalation checklist suite."""

import pytest

from myrm_agent_harness.toolkits.memory.business_templates import (
    BusinessExperienceTemplate,
    BusinessTemplateEngine,
    ChecklistStep,
    EscalationAction,
    EscalationEvaluationContext,
    EscalationReason,
    TemplateCategory,
)
from myrm_agent_harness.toolkits.memory.procedure_experience.models import (
    ProcedureMemoryEntry,
)


@pytest.fixture
def engine() -> BusinessTemplateEngine:
    return BusinessTemplateEngine()


def test_seed_templates_integrity(engine: BusinessTemplateEngine) -> None:
    """Verify that all default seeded templates for business analysis and retail exchange exist."""
    templates = engine.list_templates()
    assert len(templates) >= 3

    template_ids = {t.template_id for t in templates}
    expected_ids = {
        "BA-REV-01",
        "RET-EXC-01",
        "ESC-GATE-01",
    }
    assert expected_ids.issubset(template_ids)


def test_category_filtering(engine: BusinessTemplateEngine) -> None:
    """Verify filtering templates by category."""
    biz_templates = engine.list_templates(category=TemplateCategory.BUSINESS_ANALYSIS)
    assert len(biz_templates) >= 1
    for t in biz_templates:
        assert t.category == TemplateCategory.BUSINESS_ANALYSIS

    retail_templates = engine.list_templates(category=TemplateCategory.RETAIL_EXCHANGE)
    assert len(retail_templates) >= 1
    for t in retail_templates:
        assert t.category == TemplateCategory.RETAIL_EXCHANGE

    escalate_templates = engine.list_templates(category=TemplateCategory.ESCALATION_GATE)
    assert len(escalate_templates) >= 1
    for t in escalate_templates:
        assert t.category == TemplateCategory.ESCALATION_GATE


def test_search_templates(engine: BusinessTemplateEngine) -> None:
    """Verify searching templates by keywords in name, summary, or tags."""
    results = engine.search_templates("excel")
    assert len(results) >= 1
    assert any(t.template_id == "BA-REV-01" for t in results)

    retail_results = engine.search_templates("换货")
    assert len(retail_results) >= 1
    assert any(t.template_id == "RET-EXC-01" for t in retail_results)


def test_custom_template_registration() -> None:
    """Verify registering a custom business experience template into fresh engine."""
    custom = BusinessExperienceTemplate(
        template_id="CUSTOM-EXP-01",
        name="极速退款审核规约",
        category=TemplateCategory.RETAIL_EXCHANGE,
        summary="未发货秒退直接审批，已发货走拦截流程",
        checklist_steps=[
            ChecklistStep(
                step_index=1,
                name="核对发货状态",
                description="检查物流运单是否已生成且有走件记录",
                mandatory=True,
                validation_rule="shipping_status == 'NOT_SHIPPED'",
            )
        ],
        boundary_conditions=["仅适用于全额退款场景"],
    )
    custom_engine = BusinessTemplateEngine(initial_templates=[custom])
    retrieved = custom_engine.get_template("CUSTOM-EXP-01")
    assert retrieved is not None
    assert retrieved.name == "极速退款审核规约"
    assert len(retrieved.checklist_steps) == 1


def test_export_as_procedure_memories(engine: BusinessTemplateEngine) -> None:
    """Verify exporting business templates as standard ProcedureMemoryEntry items."""
    entries = engine.export_as_procedure_memories()
    assert len(entries) >= 3
    for entry in entries:
        assert isinstance(entry, ProcedureMemoryEntry)
        assert len(entry.procedure_steps) > 0
        assert len(entry.immutable_boundary) > 0
        assert entry.confidence == 1.0


def test_escalation_gate_normal_proceed_with_confirmation(engine: BusinessTemplateEngine) -> None:
    """Verify automated procedure proceeds with commit tool when user explicitly confirmed."""
    ctx = EscalationEvaluationContext(
        order_id="ORD-1001",
        user_id="USR-2001",
        intent="exchange_size",
        shipment_status="delivered",
        policy_clear=True,
        inventory_available=True,
        user_confirmed=True,
    )
    decision = engine.evaluate_escalation(ctx)
    assert decision.action == EscalationAction.PROCEED_AUTOMATED
    assert decision.reason == EscalationReason.NONE
    assert decision.suggested_skill_or_tool == "commit_retail_exchange"


def test_escalation_gate_normal_proceed_request_confirmation(engine: BusinessTemplateEngine) -> None:
    """Verify automated procedure requests confirmation when conditions pass but user hasn't confirmed."""
    ctx = EscalationEvaluationContext(
        order_id="ORD-1002",
        user_id="USR-2002",
        intent="exchange_size",
        shipment_status="delivered",
        policy_clear=True,
        inventory_available=True,
        user_confirmed=False,
    )
    decision = engine.evaluate_escalation(ctx)
    assert decision.action == EscalationAction.PROCEED_AUTOMATED
    assert decision.reason == EscalationReason.NONE
    assert decision.suggested_skill_or_tool == "request_user_confirmation"


def test_escalation_gate_policy_ambiguity(engine: BusinessTemplateEngine) -> None:
    """Verify policy ambiguity or custom order hard gate triggers human escalation."""
    ctx = EscalationEvaluationContext(
        order_id="ORD-1003",
        user_id="USR-2003",
        intent="exchange_custom_apparel",
        policy_clear=False,
    )
    decision = engine.evaluate_escalation(ctx)
    assert decision.action == EscalationAction.ESCALATE_TO_HUMAN
    assert decision.reason == EscalationReason.POLICY_AMBIGUITY


def test_escalation_gate_inventory_shortage(engine: BusinessTemplateEngine) -> None:
    """Verify inventory shortage triggers human escalation with out of stock suggestion."""
    ctx = EscalationEvaluationContext(
        order_id="ORD-1004",
        user_id="USR-2004",
        intent="exchange_size",
        inventory_available=False,
    )
    decision = engine.evaluate_escalation(ctx)
    assert decision.action == EscalationAction.ESCALATE_TO_HUMAN
    assert decision.reason == EscalationReason.INVENTORY_SHORTAGE
    assert decision.suggested_skill_or_tool == "escalate_out_of_stock_case"


def test_escalation_gate_repeated_dispute(engine: BusinessTemplateEngine) -> None:
    """Verify dispute count >= 2 triggers human escalation to prevent loops."""
    ctx = EscalationEvaluationContext(
        order_id="ORD-1005",
        user_id="USR-2005",
        intent="exchange_damaged",
        user_dispute_count=2,
    )
    decision = engine.evaluate_escalation(ctx)
    assert decision.action == EscalationAction.ESCALATE_TO_HUMAN
    assert decision.reason == EscalationReason.USER_DISPUTE_FAILED
    assert decision.suggested_skill_or_tool == "connect_dispute_arbitrator"


def test_record_validation_feedback(engine: BusinessTemplateEngine) -> None:
    """Verify continuous evolution feedback on templates updates counts and timestamps."""
    template = engine.get_template("BA-REV-01")
    assert template is not None
    initial_val = template.validated_count

    rec = engine.record_validation("BA-REV-01", is_validated=True, note="Operator confirmed Excel formula audit")
    assert rec is not None
    assert rec.is_validated is True
    assert template.validated_count == initial_val + 1
    assert template.last_validated_at != ""
