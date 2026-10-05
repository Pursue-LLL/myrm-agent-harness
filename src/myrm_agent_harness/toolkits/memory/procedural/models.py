"""Data models for User Intervention to Procedural Memory Distillation Engine."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class InterventionType(StrEnum):
    """Classification of human runtime intervention."""

    NEGATIVE_CONSTRAINT = "negative_constraint"
    PREREQUISITE_ENFORCEMENT = "prerequisite_enforcement"
    CORRECTIVE_ACTION = "corrective_action"
    APPROVAL_OVERRIDE = "approval_override"


class RuleScope(StrEnum):
    """Hierarchical operational scope of the distilled procedural rule."""

    WORKSPACE = "workspace"
    PROJECT = "project"
    GLOBAL = "global"
    AGENT = "agent"


class HumanInterventionEvent(BaseModel):
    """Captured runtime human intervention event triggering memory distillation."""

    event_id: str = Field(description="Unique intervention event identifier")
    session_id: str = Field(description="Session where the human interrupted or intervened")
    user_instruction: str = Field(description="Raw user interrupt or corrective prompt")
    interrupted_tool_name: str | None = Field(
        default=None,
        description="Name of tool whose invocation was interrupted or rejected",
    )
    interrupted_arguments: dict[str, str] = Field(
        default_factory=dict,
        description="Stringified arguments of the intercepted tool call",
    )
    intervention_type: InterventionType = Field(description="Categorized intervention pattern")
    workspace_root: str | None = Field(default=None, description="Active workspace path")
    timestamp: datetime = Field(description="Event capture timestamp")


class ProceduralRule(BaseModel):
    """Synthesized procedural rule distilled from human runtime interventions."""

    rule_id: str = Field(description="Unique procedural rule identifier")
    title: str = Field(description="Short semantic rule descriptor")
    rule_type: InterventionType = Field(description="Rule behavior categorization")
    scope: RuleScope = Field(default=RuleScope.WORKSPACE, description="Rule governance scope")
    scope_target: str = Field(default="", description="Identifier for target scope (e.g., workspace directory)")
    trigger_pattern: str = Field(description="Regex or substring indicating matching task/tool contexts")
    prohibited_action: str | None = Field(
        default=None,
        description="Strictly prohibited action or modification",
    )
    required_preflight: str | None = Field(
        default=None,
        description="Mandatory preflight verification step required prior to execution",
    )
    raw_instruction: str = Field(description="Source human corrective text")
    confidence: float = Field(default=0.95, ge=0.0, le=1.0, description="Rule confidence weight")
    is_active: bool = Field(default=True, description="Whether the rule is currently enforced")
    created_at: datetime = Field(description="Rule distillation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")


class RuleDistillationResult(BaseModel):
    """Summary result of distilling intervention events into procedural rules."""

    extracted_rules: list[ProceduralRule] = Field(
        default_factory=list,
        description="Newly generated or updated procedural rules",
    )
    merged_count: int = Field(default=0, ge=0, description="Number of rules consolidated or updated")
    rationale: str = Field(description="Distillation explanation and inference summary")


class RuleInjectionContext(BaseModel):
    """Assembled procedural rules packaged for agent prompt assembly and preflight gates."""

    injected_rules: list[ProceduralRule] = Field(
        default_factory=list,
        description="Matched procedural rules for the active context",
    )
    prompt_segment: str = Field(description="Formatted non-negotiable instruction string")
    enforced_preflights: list[str] = Field(
        default_factory=list,
        description="List of mandatory preflight requirements",
    )
    blocked_actions: list[str] = Field(
        default_factory=list,
        description="List of explicitly prohibited action descriptions",
    )
