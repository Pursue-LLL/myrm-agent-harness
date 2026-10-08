# [POS]: myrm_agent_harness.toolkits.memory.business_templates.__init__
# [INPUT]: .models, .seed_templates, .template_engine
# [OUTPUT]: Public exports for business_templates package

"""Business scenario experience templates and escalation checklist suite.

P0 delivery for Item 107 in topic_01 memory roadmap.

[INPUT]
- toolkits.memory.business_templates.models::BusinessExperienceTemplate, ChecklistStep, EscalationAction,
  EscalationDecision, EscalationEvaluationContext, EscalationReason, TemplateCategory, ValidationRecord (POS:
  Domain models for business experience templates and escalation checklists.)
- toolkits.memory.business_templates.seed_templates::SEED_BUSINESS_ANALYSIS_TEMPLATE,
  SEED_ESCALATION_GATE_TEMPLATE, SEED_RETAIL_EXCHANGE_TEMPLATE, SEED_TEMPLATES (POS: Pre-seeded industrial
  business experience templates.)
- toolkits.memory.business_templates.template_engine::BusinessTemplateEngine (POS: Engine coordinating
  business experience templates and escalation decision evaluations.)

[OUTPUT]
- Re-exports: TemplateCategory, EscalationReason, EscalationAction, ChecklistStep, EscalationDecision,
  EscalationEvaluationContext, ValidationRecord, BusinessExperienceTemplate, SEED_TEMPLATES,
  SEED_BUSINESS_ANALYSIS_TEMPLATE, SEED_RETAIL_EXCHANGE_TEMPLATE, SEED_ESCALATION_GATE_TEMPLATE,
  BusinessTemplateEngine, BusinessExperienceTemplateRegistry, EscalationBoundaryGate

[POS]
Business scenario experience templates and escalation checklist suite.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.business_templates.models import (
    BusinessExperienceTemplate,
    ChecklistStep,
    EscalationAction,
    EscalationDecision,
    EscalationEvaluationContext,
    EscalationReason,
    TemplateCategory,
    ValidationRecord,
)
from myrm_agent_harness.toolkits.memory.business_templates.seed_templates import (
    SEED_BUSINESS_ANALYSIS_TEMPLATE,
    SEED_ESCALATION_GATE_TEMPLATE,
    SEED_RETAIL_EXCHANGE_TEMPLATE,
    SEED_TEMPLATES,
)
from myrm_agent_harness.toolkits.memory.business_templates.template_engine import (
    BusinessTemplateEngine,
)

BusinessExperienceTemplateRegistry = BusinessTemplateEngine
EscalationBoundaryGate = BusinessTemplateEngine

__all__ = [
    "TemplateCategory",
    "EscalationReason",
    "EscalationAction",
    "ChecklistStep",
    "EscalationDecision",
    "EscalationEvaluationContext",
    "ValidationRecord",
    "BusinessExperienceTemplate",
    "SEED_TEMPLATES",
    "SEED_BUSINESS_ANALYSIS_TEMPLATE",
    "SEED_RETAIL_EXCHANGE_TEMPLATE",
    "SEED_ESCALATION_GATE_TEMPLATE",
    "BusinessTemplateEngine",
    "BusinessExperienceTemplateRegistry",
    "EscalationBoundaryGate",
]
