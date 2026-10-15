from enum import StrEnum

from pydantic import BaseModel, Field


class TaskComplexityCategory(StrEnum):
    SIMPLE_SINGLE_STEP = "simple_single_step"
    EXPLORATORY_CHAT = "exploratory_chat"
    STRICTLY_SEQUENTIAL = "strictly_sequential"
    PARALLEL_HEAVYWEIGHT = "parallel_heavyweight"


class TriageVerdict(StrEnum):
    ADMIT_GRAPH = "admit_graph"
    REJECT_TO_SINGLE_AGENT = "reject_to_single_agent"
    REJECT_TO_CONVERSATIONAL = "reject_to_conversational"
    REJECT_TO_LINEAR_PIPELINE = "reject_to_linear_pipeline"


class BudgetStatus(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    EXHAUSTED = "exhausted"


class TriageFeatureVector(BaseModel):
    prompt_length: int = Field(ge=0, description="Length of prompt text in characters")
    declared_subtasks_count: int = Field(ge=0, description="Count of parsed subtasks")
    independent_parallel_count: int = Field(ge=0, description="Count of independent subtasks without dependencies")
    max_dependency_depth: int = Field(ge=0, description="Maximum depth of task dependency chain")
    is_conversational_inquiry: bool = Field(default=False, description="Flag indicating open-ended exploratory chat")
    has_isolated_heavyweight_steps: bool = Field(default=False, description="Whether steps require heavy compute")


class GraphTriageDecision(BaseModel):
    verdict: TriageVerdict
    category: TaskComplexityCategory
    reason: str
    recommended_mode: str
    estimated_speedup_ratio: float = Field(default=1.0, ge=0.1)
    estimated_tokens_saved: int = Field(default=0, ge=0)
    features: TriageFeatureVector


class BudgetCapConfig(BaseModel):
    max_tokens: int = Field(default=500_000, ge=1_000, description="Hard cap on tokens")
    max_cost_usd: float = Field(default=5.0, ge=0.01, description="Hard cap on cost in USD")
    warning_threshold_pct: float = Field(default=0.3, ge=0.01, le=0.9, description="Remaining pct threshold for warning")
    critical_threshold_pct: float = Field(default=0.1, ge=0.001, le=0.5, description="Remaining pct threshold for critical")
    auto_reduce_on_critical: bool = Field(default=True, description="Whether to trigger partial early reduce on critical")


class ExecutionSpendState(BaseModel):
    session_id: str
    current_tokens: int = Field(default=0, ge=0)
    current_cost_usd: float = Field(default=0.0, ge=0.0)
    remaining_tokens: int = Field(default=500_000, ge=0)
    remaining_budget_pct: float = Field(default=1.0, ge=0.0, le=1.0)
    budget_status: BudgetStatus = Field(default=BudgetStatus.HEALTHY)
    active_concurrency: int = Field(default=4, ge=0)
    is_throttled: bool = Field(default=False)
    is_circuit_broken: bool = Field(default=False)


class PartialNodeOutput(BaseModel):
    node_id: str
    status: str = Field(description="'completed', 'running', 'pending'")
    result_summary: str = Field(default="")
    tokens_used: int = Field(default=0, ge=0)


class PartialReduceReport(BaseModel):
    session_id: str
    summary: str
    completed_nodes: list[str] = Field(default_factory=list)
    unexecuted_nodes: list[str] = Field(default_factory=list)
    tokens_spent: int = Field(ge=0)
    tokens_saved: int = Field(ge=0)
    delivery_confidence: float = Field(ge=0.0, le=1.0)
    reason: str
