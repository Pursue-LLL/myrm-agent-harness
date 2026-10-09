"""Types and contracts for workspace inline deck and multi-model cost arbitrage.

[INPUT]
- None (pure type definitions and immutable data contracts).

[OUTPUT]
- Exports enumeration classes and dataclasses for widget management,
  cost arbitrage routing, dual persona switching, and budget guarding.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.workspace_arbitrage
- Module: arbitrage_types.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence


class DeckWidgetType(str, Enum):
    """Supported interactive widget types embedded directly inside chat messages."""

    PARAM_SLIDER = "param_slider"
    STEP_APPROVAL = "step_approval"
    DIFF_VIEW = "diff_view"
    MICRO_TERMINAL = "micro_terminal"


class DeckWidgetState(str, Enum):
    """Operational lifecycle state of an inline chat deck widget."""

    PENDING = "pending"
    ACTIVE = "active"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class ModelArbitrageTier(str, Enum):
    """Tiering definition for cost-performance model arbitrage."""

    L1_FAST_LOCAL = "l1_fast_local"
    L2_FLAGSHIP_REASONING = "l2_flagship_reasoning"


class PersonaMode(str, Enum):
    """Dual-persona operational modes for agent demeanor."""

    PROFESSIONAL = "professional"
    COMPANION = "companion"


class BudgetWatermarkLevel(str, Enum):
    """Watermark status indicator for runtime session budget guarding."""

    NORMAL = "normal"
    SOFT_WARNING_80 = "soft_warning_80"
    HARD_FUSED_100 = "hard_fused_100"


@dataclass(frozen=True)
class DeckWidgetSpec:
    """Specification of an interactive widget embedded in an inline chat deck."""

    widget_id: str
    message_id: str
    widget_type: DeckWidgetType
    title: str
    initial_payload: Mapping[str, str] = field(default_factory=dict)
    state: DeckWidgetState = DeckWidgetState.PENDING
    created_at_epoch: float = 0.0


@dataclass(frozen=True)
class DeckInteractionEvent:
    """An interaction action dispatched from user action on an inline widget."""

    widget_id: str
    action_name: str
    parameters: Mapping[str, str] = field(default_factory=dict)
    triggered_at_epoch: float = 0.0


@dataclass(frozen=True)
class DeckActionResult:
    """Result returned after evaluating an inline widget interaction."""

    widget_id: str
    new_state: DeckWidgetState
    feedback_message: str
    result_payload: Mapping[str, str] = field(default_factory=dict)
    success: bool = True


@dataclass(frozen=True)
class ComplexityScore:
    """Multi-dimensional complexity evaluation result for user task."""

    composite_score: float  # 0.0 (trivial) to 1.0 (extreme reasoning)
    reasons: Sequence[str] = field(default_factory=tuple)
    is_code_heavy: bool = False
    is_multi_step_planning: bool = False


@dataclass(frozen=True)
class RoutingDecision:
    """Decision made by the cost-performance arbitrage router."""

    selected_tier: ModelArbitrageTier
    target_model_name: str
    estimated_input_tokens: int
    complexity: ComplexityScore
    promoted_from_l1: bool = False
    decision_reason: str = ""


@dataclass(frozen=True)
class CostSavingsRecord:
    """Record tracking estimated financial savings from multi-model arbitrage."""

    session_id: str
    l1_actual_cost_usd: float
    baseline_l2_cost_usd: float
    saved_usd: float
    saving_ratio: float


@dataclass(frozen=True)
class ModelFingerprintProfile:
    """Profile describing vendor response fingerprint and degradation signals."""

    model_name: str
    system_fingerprint: str
    latency_ms: float
    output_token_count: int
    is_truncated: bool = False
    detected_drift: bool = False


@dataclass(frozen=True)
class BudgetWatermarkStatus:
    """Current consumption and safety watermark for a session budget."""

    session_id: str
    budget_limit_usd: float
    consumed_usd: float
    consumption_percentage: float
    watermark_level: BudgetWatermarkLevel
    enforce_fallback_to_local: bool = False


@dataclass(frozen=True)
class WorkspaceArbitrageConfig:
    """Master configuration for the workspace arbitrage suite."""

    l1_default_model: str = "deepseek-chat-fast"
    l2_default_model: str = "claude-3-7-sonnet"
    local_fallback_model: str = "ollama-qwen2.5-coder-7b"
    complexity_threshold_for_l2: float = 0.55
    soft_budget_warning_ratio: float = 0.80
    hard_budget_fuse_ratio: float = 1.00
    default_session_budget_usd: float = 10.00
    baseline_l2_price_per_1k_tokens: float = 0.015
    l1_price_per_1k_tokens: float = 0.0014
