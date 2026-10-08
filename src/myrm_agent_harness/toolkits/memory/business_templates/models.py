"""Domain models for business experience templates and escalation checklists.

P0 delivery for Item 107 in topic_01 memory roadmap.
Supports business analysis review procedures and retail exchange checklists with human escalation gates.

[INPUT]
- Third-party: pydantic

[OUTPUT]
- TemplateCategory: Category of business experience templates.
- EscalationReason: Reason for triggering human escalation.
- EscalationAction: Decision action of the escalation gate.
- ChecklistStep: A discrete step in an operational checklist.
- EscalationDecision: Decision evaluated by the escalation boundary gate.
- EscalationEvaluationContext: Contextual parameters evaluated by the escalation gate.
- ValidationRecord: Record of continuous feedback and validation for an experience template.
- BusinessExperienceTemplate: Standardized business experience template for operational cold start and reuse.

[POS]
Domain models for business experience templates and escalation checklists.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class TemplateCategory(StrEnum):
    """Category of business experience templates."""

    BUSINESS_ANALYSIS = "business_analysis"
    RETAIL_EXCHANGE = "retail_exchange"
    ESCALATION_GATE = "escalation_gate"


class EscalationReason(StrEnum):
    """Reason for triggering human escalation."""

    NONE = "none"
    POLICY_AMBIGUITY = "policy_ambiguity"
    INVENTORY_SHORTAGE = "inventory_shortage"
    USER_DISPUTE_FAILED = "user_dispute_failed"
    ANOMALOUS_ORDER = "anomalous_order"
    EXCEEDS_AUTHORITY = "exceeds_authority"


class EscalationAction(StrEnum):
    """Decision action of the escalation gate."""

    PROCEED_AUTOMATED = "proceed_automated"
    ESCALATE_TO_HUMAN = "escalate_to_human"


class ChecklistStep(BaseModel):
    """A discrete step in an operational checklist."""

    step_index: int = Field(description="1-based step index")
    name: str = Field(description="Step title")
    description: str = Field(description="Operational guidance for this step")
    mandatory: bool = Field(default=True, description="Whether this step must pass before next")
    validation_rule: str = Field(description="Criteria or predicate to verify step completion")


class EscalationDecision(BaseModel):
    """Decision evaluated by the escalation boundary gate."""

    action: EscalationAction = Field(description="Proceed or escalate to human")
    reason: EscalationReason = Field(default=EscalationReason.NONE, description="Categorical reason for escalation")
    message: str = Field(description="Human readable explanation")
    required_context: dict[str, str] = Field(default_factory=dict, description="Context variables collected for human agent")
    suggested_skill_or_tool: str = Field(default="", description="Next recommended skill or routing target")


class EscalationEvaluationContext(BaseModel):
    """Contextual parameters evaluated by the escalation gate."""

    order_id: str | None = Field(default=None, description="Target order identifier")
    user_id: str | None = Field(default=None, description="Customer or actor identifier")
    intent: str = Field(default="", description="Customer intent or request description")
    shipment_status: str = Field(default="delivered", description="Current shipment fulfillment state")
    warranty_valid: bool = Field(default=True, description="Whether item is within warranty/exchange window")
    inventory_available: bool = Field(default=True, description="Whether target exchange SKU has sufficient stock")
    user_dispute_count: int = Field(default=0, description="Number of times customer disputed or corrected the agent")
    is_custom_order: bool = Field(default=False, description="Whether this item is customized or non-refundable")
    policy_clear: bool = Field(default=True, description="Whether applicable return/exchange policy is unambiguous")
    user_confirmed: bool = Field(default=False, description="Whether user explicitly confirmed exchange parameters")


class ValidationRecord(BaseModel):
    """Record of continuous feedback and validation for an experience template."""

    record_id: str = Field(description="Unique record identifier")
    template_id: str = Field(description="Target template identifier")
    is_validated: bool = Field(description="True if validation succeeded, False if rejected")
    note: str = Field(default="", description="Optional operator or execution notes")
    timestamp: str = Field(description="ISO 8601 timestamp of validation event")


class BusinessExperienceTemplate(BaseModel):
    """Standardized business experience template for operational cold start and reuse."""

    template_id: str = Field(description="Unique identifier of the template")
    name: str = Field(description="Human-readable template name")
    category: TemplateCategory = Field(description="Business scenario category")
    summary: str = Field(description="High-level description of the review method or procedure")
    checklist_steps: list[ChecklistStep] = Field(default_factory=list, description="Ordered checklist steps")
    boundary_conditions: list[str] = Field(default_factory=list, description="Preconditions and boundary constraints")
    sample_trajectory_ref: str = Field(default="", description="Reference session or trajectory identifier")
    version: str = Field(default="1.0.0", description="Semantic version of the template")
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    metadata: dict[str, str] = Field(default_factory=dict, description="Custom metadata key-value pairs")
    validated_count: int = Field(default=0, description="Cumulative count of successful application confirmations")
    rejected_count: int = Field(default=0, description="Cumulative count of failed or disputed applications")
    last_validated_at: str | None = Field(default=None, description="ISO timestamp of last validation")
