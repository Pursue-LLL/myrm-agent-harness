"""Domain models and contracts for subtask boundary online context compaction and economics.

[INPUT]
- None (Self-contained strongly-typed domain definitions).

[OUTPUT]
- CompactionEconomicsConfig: Configuration parameters for window reserves and economic margins.
- PlanStepStatus: Enum defining lifecycle phases of plan steps/subtasks.
- PlanStep: Typed descriptor of an individual task step in the agent plan.
- CompactionDecisionResult: Rigorous verdict evaluating whether compaction yields net positive economics.
- EconomicCompactionLedger: Tracking ledger for carried compaction debt and lifetime token savings.
- ContinuationTurnPayload: Package containing memo summary and continuation state for the new turn.

[POS]
Domain layer powering NVIDIA SoL-Pi inspired economic breakeven compaction and subtask boundary hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class PlanStepStatus(str, Enum):
    """Lifecycle status of an individual execution plan step."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PlanStep:
    """Descriptor of a planned subtask step."""

    step_id: str
    title: str
    status: PlanStepStatus = PlanStepStatus.PENDING
    requests_spent: int = 0
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CompactionEconomicsConfig:
    """Mathematical thresholds and safety margins governing compaction decisions."""

    window_reserve_tokens: int = 16_384  # Hard reserve to prevent 400 Context Window Exceeded
    max_context_tokens: int = 128_000  # Total context window capacity
    first_compaction_request_scale: float = 2.0  # Scale factor for initial request rate
    subsequent_compaction_margin: float = 1.5  # Safety multiplier: horizon >= breakeven * margin
    default_estimated_memo_tokens: int = 800  # Expected size of generated compacted summary
    default_estimated_write_tokens: int = 2400  # Tokens spent invoking LLM to write compaction summary


@dataclass(frozen=True)
class CompactionDecisionResult:
    """Rigorous verdict evaluating whether compaction yields net positive economics."""

    should_compact: bool
    reason_code: str  # HARD_WINDOW_PRESSURE | ECONOMIC_BREAKEVEN_APPROVED | INSUFFICIENT_HORIZON_REJECTED | DEBT_UNRECOVERED_REJECTED | NO_COMPACTION_NEEDED
    breakeven_requests: int
    combined_breakeven_requests: int
    effective_horizon_requests: int
    carried_debt_tokens: int
    net_estimated_savings: int
    explanation: str


@dataclass
class EconomicCompactionLedger:
    """Cumulative ledger tracking amortized compaction debt and lifetime savings."""

    total_compactions: int = 0
    carried_debt_tokens: int = 0
    lifetime_tokens_saved: int = 0
    last_compaction_tokens: int = 0


@dataclass(frozen=True)
class ContinuationTurnPayload:
    """Payload seamlessly launching a fresh new turn post-compaction."""

    new_turn_number: int
    memo_summary: str
    remaining_steps: Sequence[PlanStep]
    continuation_prompt: str
