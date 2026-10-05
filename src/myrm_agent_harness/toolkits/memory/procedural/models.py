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


class EngineeringRuleSeverity(StrEnum):
    """Severity classification for engineering procedural rule violations."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ConstraintBoundary(BaseModel):
    """Quantitative or categorical boundary defining engineering manufacturing limits."""

    min_value: float | None = Field(default=None, description="Lower inclusive threshold")
    max_value: float | None = Field(default=None, description="Upper inclusive threshold")
    allowed_values: list[str] | None = Field(default=None, description="Permissible discrete set")
    unit: str | None = Field(default=None, description="Engineering physical unit (e.g., 'mm', 'mil')")


class EngineeringProceduralRule(BaseModel):
    """Immutable domain engineering procedural specification governing agent workflow execution."""

    rule_id: str = Field(description="Unique rule identifier (e.g., 'pcb_drc_min_trace_width')")
    domain: str = Field(description="Vertical engineering domain (e.g., 'pcb_drc', 'eda_routing')")
    version: str = Field(default="1.0.0", description="Semantic rule specification version")
    parameter_name: str = Field(description="Target design parameter or configuration key")
    boundary: ConstraintBoundary = Field(description="Physical tolerance and validity bounds")
    description: str = Field(description="Formal engineering rationale and physical rule context")
    severity: EngineeringRuleSeverity = Field(
        default=EngineeringRuleSeverity.ERROR,
        description="Violation impact level",
    )
    fix_suggestion: str | None = Field(
        default=None,
        description="Automated corrective adjustment suggestion if breached",
    )
    precondition_tags: list[str] = Field(
        default_factory=list,
        description="Context tags required to activate this rule",
    )
    created_at: datetime = Field(description="Registration timestamp")


class RuleEvaluationResult(BaseModel):
    """Diagnostic outcome of evaluating an engineering design parameter against a procedural rule."""

    rule_id: str = Field(description="Evaluated rule identifier")
    parameter_name: str = Field(description="Inspected parameter key")
    passed: bool = Field(description="Whether the parameter satisfies the engineering boundary")
    severity: EngineeringRuleSeverity = Field(description="Assigned violation severity")
    actual_value: str | float | int | bool | None = Field(
        default=None,
        description="Value inspected during evaluation",
    )
    violation_message: str | None = Field(
        default=None,
        description="Explanation when boundary check fails",
    )
    suggested_value: str | float | int | bool | None = Field(
        default=None,
        description="Automatic correction candidate value",
    )


class PreflightCheckReport(BaseModel):
    """Comprehensive DRC/engineering preflight gate evaluation report."""

    domain: str = Field(description="Evaluated vertical engineering domain")
    total_rules_checked: int = Field(ge=0, description="Number of rules evaluated")
    passed: bool = Field(description="Whether all blocking rules passed without errors")
    violations: list[RuleEvaluationResult] = Field(
        default_factory=list,
        description="List of blocking errors that abort execution",
    )
    warnings: list[RuleEvaluationResult] = Field(
        default_factory=list,
        description="List of non-blocking warnings",
    )
    recommended_fixes: dict[str, str | float | int | bool] = Field(
        default_factory=dict,
        description="Key-value mapping of proposed parameter corrections",
    )

